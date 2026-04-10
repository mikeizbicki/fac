# stdlib imports
from collections import defaultdict
import asyncio
import itertools
import os

# external imports
import yaml

# project imports
from fac.BuildContext import BuildContext
from fac.Config import load_config
from fac.Errors import DirtyRepo, FACError
from fac.FileManager import FileManager
from fac.Job import Job, assert_git_sane
from fac.util.FastAPI import Routable, route
from fac.util.freeze import freeze
from fac.util.targets import match_pattern_starstar, extract_variables, substitute_variables, variables_transitive_substitute
from fac.util.variables import eval_var

# setup logging
import logging
from fac.Logging import logger, with_subtree
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)


class Fac(Routable):
    '''
    The build system should be thought of like a state machine,
    where the contexts* attributes represent the different states a context can be in.
    The main work of this class is done in the process_* methods,
    which process the contexts in the corresponding state.
    '''
    def __init__(
            self,
            config_file='fac.yaml',
            allow_dirty=False,
            auto_commit=True,
            print_prompt=False,
            ):
        super().__init__()

        # set git-related configuration
        self.auto_commit = auto_commit
        if not auto_commit:
            allow_dirty = True
        self.allow_dirty = allow_dirty
        assert_git_sane(allow_dirty)

        # set default values for controlling runtime behavior
        self._max_workers = 4
        self._parallel_build = True
        self._do_assert_invariants = False
        self._print_prompt = print_prompt
        self._print_states_when_building = False

        # FIXME:
        # we need our own dedicated event loop here because
        # we are mixing async/sync code;
        # eventually we should move the whole interface to async to fix this wart
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # create important variables
        self.targets_dict = load_config(config_file)

        # the states
        self.contexts = {
            'unresolved': set(),
            'buildable': set(),
            'waiting': set(),
            'building': set(),
            'built': set(),
            'notbuilt': set(),
            'build_required': set(),
        }
        self.path2context = {}

        # every built context has a dependencies_built field that stores the paths
        # that were needed to build the context;
        # self.rdeps is a lookup for the reverse direction;
        # the keys are paths, and the values are the paths built from the key
        self.rdeps = defaultdict(lambda: set())

        # store the full dependency graph of BuildContext instances
        # keys: a BuildContext
        # values: a list of BuildContext instances that require the key
        self.required_for = defaultdict(lambda: [])

        self._init_jobs()

    ########################################
    # primary public interface
    ########################################

    @route('/add_target', ['POST'])
    def add_target(
            self,
            target: str,
            required_for=None,
            include_prompt=None,
            include_old=False,
            include_paths=None,
            mode='build',
            ):
        '''
        Registers a target with the build system.

        Arguments:
        - target (str): the target to be built; all variables must be specified; supports globstar (**)-style pattern matching
        - include_prompt (str): allows specifying additional build instructions for the target
        - include_old (bool): should the old file be included if rebuilding?
        - mode (str):
            - "build": (default) build the file only if needed
            - "overwrite": always build the file, overwriting existing contents
            - "dryrun": register the file with the build system, but do not build
        '''
        matches = match_pattern_starstar(self.targets_dict, target)

        if len(matches) == 0:
            logger.error(f'target {target} has no match in fac.yaml')
            raise FACError()

        # get job info
        if required_for is None:
            str_mode = ''
            if mode == 'overwrite':
                str_mode = ' --overwrite'
            if mode == 'dryrun':
                str_mode = ' --dryrun'
            str_include_prompt = ''
            if include_prompt:
                str_include_prompt = f' --include_prompt={str(include_prompt)}'
            str_include_old = ''
            if include_old:
                str_include_old = f' --include_old={str(include_old)}'
            str_include_paths = ''
            if include_paths:
                str_include_paths = f' --include_paths={str(include_paths)}'
            build_cmd = f'fac {target}{str_mode}{str_include_prompt}{str_include_old}{str_include_paths}'
            job = Job(build_cmd, auto_commit=self.auto_commit)
            self.jobs['running'].add(job)
        else:
            job = self.context_to_job[required_for]

        # create the contexts
        for normalized_target, target_env in matches:

            # variables_unresolved starts off the config,
            # but we pre-resolve every variable in target_env
            variables_unresolved = dict(self.targets_dict[normalized_target]['variables'])
            for var in target_env:
                if var in variables_unresolved:
                    del variables_unresolved[var]

            # build the context
            context = BuildContext(
                    normalized_target=normalized_target,
                    config=self.targets_dict[normalized_target],
                    variables_resolved=target_env,
                    variables_unresolved=variables_unresolved,
                    dependencies_built=[],
                    dependencies_building=[],
                    dependencies_unresolved=self.targets_dict[normalized_target]['dependencies'],
                    include_prompt=include_prompt,
                    include_old=include_old,
                    include_paths=include_paths,
                    mode=mode,
                    )
            self._add_context(context, required_for=required_for, force_add=False, job=job)

    def build_all(self):
        # NOTE:
        # we will store a hash of self.contexts at every iteration;
        # we will use this set to ensure that we don't get stuck
        # in an infinite loop repeating the same cycle of states forever;
        # the original/main purpose of these checks
        # is to catch bugs in the build system;
        state_hashes = set()
        def state_hash():
            return hash(freeze(self.contexts))

        def debug_print(s):
            if self._print_states_when_building:
                self.debug_print(s)

        with logger.make_subtree():
            debug_print(f'iter={len(state_hashes)}')
            while any([
                    len(self.contexts['unresolved']) > 0,
                    len(self.contexts['buildable']) > 0,
                    len(self.contexts['waiting']) > 0,
                    ]):

                state0 = state_hash()
                state1 = None

                # perform all context state transitions
                while state0 != state1:
                    self.process_all_dependencies()
                    debug_print(f'iter={len(state_hashes)} -- dependencies')
                    self.assert_invariants()

                    self.process_all_variable()
                    debug_print(f'iter={len(state_hashes)} -- variable')
                    self.assert_invariants()

                    self.process_all_waiting()
                    debug_print(f'iter={len(state_hashes)} -- waiting')
                    self.assert_invariants()

                    self.process_all_buildable()
                    debug_print(f'iter={len(state_hashes)} -- buildable')
                    self.assert_invariants()

                    state1 = state0
                    state0 = state_hash()

                self.process_all_build_required()
                debug_print(f'iter={len(state_hashes)} -- build_required')
                self.assert_invariants()

                # now that we have built some contexts,
                # we should allow any jobs
                self._finalize_jobs()

                # perform duplicate state check
                if state0 in state_hashes:
                    all_dryrun = True
                    for context in itertools.chain(
                            self.contexts['buildable'],
                            self.contexts['waiting'],
                            self.contexts['unresolved'],
                            ):
                        if context.mode != 'dryrun':
                            all_dryrun = False
                    if not all_dryrun:
                        logger.error('duplicate state detected --- this is a bug in fac')
                    else:
                        logger.info('evaluated as far as dryrun will allow')
                    break
                state_hashes.add(state0)
            self._finalize_jobs()

    ########################################
    # jobs
    ########################################
    
    def _init_jobs(self):
        # the keys are states and the values are the jobs in that state
        self.jobs: dict[str, set[Job]] = {
            'queued': set(),
            'running': set(),
            'failed': set(),
            'succeeded': set(),
            }

        self.context_to_job = {}
        self.path_to_job = {}
        self.jobs_callbacks = []

    def assert_invariants_jobs(self):
        # job can be in more than one state
        for job in self.jobs['running']:
            assert job not in self.jobs['queued']
            assert job not in self.jobs['failed']
            assert job not in self.jobs['succeeded']

        # every context/path is in a job
        for state_name in ['unresolved', 'buildable', 'waiting', 'built']:
            for context in self.contexts[state_name]:
                assert context in self.context_to_job
                assert context in self.context_to_job[context].contexts
                if context.path_safe():
                    assert context.path in self.path_to_job
                    assert context.path in self.path_to_job[context.path].paths

    def add_callback(self, f):
        self.jobs_callbacks.append(f)

    def run_callbacks(self):
        for f in self.jobs_callbacks:
            f()

    def get_jobs(self):
        ret = []
        for state, jobs in self.jobs.items():
            for job in jobs:
                job_dict = {
                    'job_id': job.job_id,
                    'state': state,
                    'enqueued_time': job.start_time,
                    'start_time': job.start_time,
                    'end_time': job.end_time,
                    'paths': [ {
                        'path': path,
                        'status': 'building' if state == 'running' else 'up-to-date',
                        'mode': 'build',
                        }
                        for path in job.paths
                        ],
                    }
                ret.append(job_dict)
        return ret

    def _finalize_jobs(self):
        self.assert_invariants_jobs()
        jobs_running = self.jobs['running']
        self.jobs['running'] = set()
        for job in jobs_running:
            done = True
            for context in job.contexts:
                if context in self.contexts['unresolved']:
                    done = False
                if context in self.contexts['buildable']:
                    done = False
                if context in self.contexts['waiting'] and context.mode != 'dryrun':
                    done = False
            if done:
                logger.info(f'finalizing job {job.job_id}')
                job.finalize()
                self.jobs['succeeded'].add(job)
                self.run_callbacks()
            else:
                self.jobs['running'].add(job)
        self.assert_invariants_jobs()

    ########################################
    # sanity checking
    ########################################

    def assert_invariants(self):
        if self._do_assert_invariants:
            # no context can be in more than one state
            for state1 in self.contexts.keys():
                for state2 in self.contexts.keys():
                    if state1 != state2:
                        for context in self.contexts[state1]:
                            assert context not in self.contexts[state2], f'state1={state1}, state2={state2}, context={context}'

            # ensure every path has a context and vice versa
            for state in self.contexts:
                for context in self.contexts[state]:
                    if context.path_safe():
                        assert context.path_safe() in self.path2context
            '''
                        assert self.path2context[context.path_safe()] == context
            for context in self.path2context.values():
                assert any([context in self.contexts[state] for state in self.contexts])

            # no path can be in more than one context
            for state1 in self.contexts.keys():
                for context1 in self.contexts[state1]:
                    if context1.path_safe():
                        for state2 in self.contexts.keys():
                            for context2 in self.contexts[state2]:
                                if context2.path_safe():
                                    if context1 != context2:
                                        assert context1.path != context2.path
            '''
            # FIXME:
            # the checks above seem intuitively good to me;
            # but the break the recursive test cases for some reason,
            # and that needs fixing


    ########################################
    # visualize state
    ########################################

    @route('/get_states', ['GET'])
    def get_states(self, show_len=False):
        '''
        Returns the internal state of the build system.
        This is for debugging purposes only and no web service should rely on this endpoint.
        '''
        f = lambda x: x
        if show_len:
            f = len
        return {
            'contexts_unresolved': f(self.contexts['unresolved']),
            'contexts_buildable': f(self.contexts['buildable']),
            'contexts_waiting': f(self.contexts['waiting']),
            'contexts_built': f(self.contexts['built']),
            'contexts_notbuilt': f(self.contexts['notbuilt']),
            }

    def debug_short(self, submessage=False):
        logger.debug({'BuildState': {
            'len(self.contexts[unresolved])': len(self.contexts['unresolved']),
            'len(self.contexts[buildable])': len(self.contexts['buildable']),
            'len(self.contexts[waiting])': len(self.contexts['waiting']),
            'len(self.contexts[built])': len(self.contexts['built']),
            }}, submessage=submessage)

    def _state_as_dict(self, longform=True):
        '''
        Convert the internal state into dictionary suitable for yaml conversion.
        '''
        if longform:
            yaml_dict = {k: [context.to_dict() for context in contexts] for k, contexts in self.contexts}
        else:
            yaml_dict = {k: sorted([context.denormalized_target() for context in contexts]) for k, contexts in self.contexts}
        return yaml_dict

    def debug_print(self, msg=None):
        '''
        Shows a human-readable yaml-like version of the state that each context is in.
        '''
        if msg:
            msg_str = f'({msg[:21]})'
            msg_str += ' ' * (23 - len(msg_str))
        else:
            msg_str = ' '*23
        print(40 * '=')
        print(f'|| BuildState {msg_str} ||')
        print(40 * '=')
        print(yaml.dump(self._state_as_dict(), default_flow_style=False, sort_keys=False))

    ########################################
    # state transition methods
    ########################################

    def _get_built_paths(self):
        return [context.path for context in self.contexts['built']]

    def _set_context_state(self, context, state):
        '''
        This helper function should be used when assigning a context to a state
        instead of directly running self.contexts[state].add()
        '''
        self.contexts[state].add(context)
        if context.path_safe():
            self.path2context[context.path] = context
            for dep in context.dependencies_built:
                self.rdeps[dep['target']].add(context.path)

    def _add_context(
            self,
            context: BuildContext,
            required_for: BuildContext,
            force_add=True,
            job=None,
            ):
        '''
        A context should never be added directly to one of the states,
        and this method should be used instead.
        This method ensures that:
        1. the context is placed in the correct state
        2. the context is split into multiple contexts if needed
            (this happens when variable definitions contain newlines)
        3. reverse dependencies are tracked correctly
        4. contexts are only added if they actually need to be built
            (this is a performance optimization and not needed for correctness)

        Arguments:
            context: the context to be added to the system
            required_for: the reverse dependency that created this context
            force_add:
                - if False, then context will not be added if it already exists
                - if True, then the context will always be added
                  NOTE:
                  Set to True only when the context has been "temporarily removed" from a state for processing.
        '''
        def maybe_add(state_name):
            # helper function that tracks which contexts have been added;
            # because contexts are immutable:
            # if the same context has been added to the same state,
            # and the actions of that state do not depend on IO,
            # we know that the same result will happen,
            # and so we do not need to recompute the context
            #
            # using maybe_add to prevent duplicates is not required for correctness;
            # it is a memoization-like optimization that speeds up the build system
            #
            # for this optimization to be correct,
            # we require that variable evaluation be idempotent and side-effect-free
            if not hasattr(self, '_contexts_history'):
                self._contexts_history = set()
            if not force_add and (state_name, context) in self._contexts_history:
                return
            self._contexts_history.add((state_name, context))
            self._set_context_state(context, state_name)

        if context != required_for:
            self.required_for[context].append(required_for)

        context_orig = context
        for context in context.split():
            if context_orig != context:
                self.required_for[context].append(context_orig)

            # register context with current job
            if job is None:
                job = self.context_to_job[required_for]
            job.register_context(context)
            self.context_to_job[context] = job
            if context.path_safe():
                self.path_to_job[context.path_safe()] = job

            # if we've already built the context,
            # do not add it anywhere
            if context in self.contexts['built']:
                return

            # if we haven't built the context,
            # then put it in the appropriate state
            if len(context.dependencies_building) > 0:
                maybe_add('waiting')
            else:
                if (len(context.variables_unresolved) == 0 and
                   len(context.dependencies_unresolved) == 0):
                    maybe_add('buildable')
                else:
                    maybe_add('unresolved')

    def process_all_waiting(self):
        logger.debug('process_all_waiting()')
        self.debug_short(submessage=True)
        waiting0 = self.contexts['waiting']
        self.contexts['waiting'] = set()
        for context in waiting0:
            self.process_waiting(context, waiting0)
        self.debug_short(submessage=True)

    @with_subtree(logger)
    def process_waiting(self, context, waiting0):
        logger.debug('process_waiting()')
        logger.debug({'context': context.to_dict()}, submessage=True)
        dependencies_built1 = list(context.dependencies_built)
        dependencies_building1 = []
        for dep_building in context.dependencies_building:
            denormalized_targets = substitute_variables(dep_building['target'], context.variables_resolved)
            for denormalized_target in denormalized_targets:
                # denormalized_target is a path whenever it does not contain '$';
                # paths and targets must be handled differently
                if '$' not in denormalized_target:
                    path = denormalized_target
                    if path in self._get_built_paths():
                        dep1 = dict(dep_building)
                        dep1['target'] = path
                        dependencies_built1.append(dep1)
                    else:
                        dependencies_building1.append(dep_building)

                else:
                    # some dependencies will never resolve to files;
                    # this happens when the required variables
                    # are not defined within the context
                    # but instead within the dependency;
                    # to determine if these dependencies are actually built,
                    # we search through all context_* states
                    # and check if there are any non-built matches
                    all_targets_built = True
                    for loop_context in itertools.chain(
                            self.contexts['unresolved'],
                            self.contexts['buildable'],
                            self.contexts['waiting'],
                            waiting0,
                            ):
                        if denormalized_target == loop_context.normalized_target and loop_context != context:
                            all_targets_built = False
                    if not all_targets_built:
                        dependencies_building1.append(dep_building)
                    else:
                        for loop_context in self.contexts['built']:
                            matches = match_pattern_starstar(freeze([dep_building['target']]), loop_context.path)
                            #matches = match_pattern_starstar(dep_targets, loop_context.path)
                            if len(matches) == 1:
                                # FIXME:
                                # the if statement is needed for when fac builds more than one target at a time
                                # (either through demon mode or multiple cmd line args)
                                # in that case, states['built'] will contain paths that do not necessarily correspond to the current context,
                                # and the if statement ensures that only those paths for this context will be added;
                                # the problem (and thing to fix) is that the match_pattern_starstar function is slow
                                # and should not be in an inner loop
                                dep1 = dict(dep_building)
                                dep1['target'] = loop_context.path
                                dependencies_built1.append(freeze(dep1))
                                assert '$' not in dep1['target']
        context1 = context.model_copy(update={
            'dependencies_built': dependencies_built1,
            'dependencies_building': dependencies_building1,
            })
        self._add_context(context1, required_for=context, force_add=context1==context)
        self.assert_invariants()

    def trace_required_for(self, context, denormalize_targets=False, collapse=True):
        ret = {}
        for rdep in self.required_for[context]:
            dispvals = []
            if rdep:
                if denormalize_targets:
                    dispvals = rdep.denormalized_target()
                else:
                    dispvals = [rdep.normalized_target]
            else:
                return '<user_action>'
            for dispval in dispvals:
                ret[dispval] = {}
                if rdep == context:
                    ret[dispval]['<self>'] = True
                else:
                    recursion = self.trace_required_for(rdep)
                    if recursion == '<user_action>':
                        ret[dispval]['<user_action>'] = True
                    else:
                        ret[dispval] |= recursion
        return ret

    def process_all_buildable(self):
        logger.debug('process_all_buildable()')

        for context in self.contexts['buildable']:
            status, do_build = context.get_status()

            # print debug info
            logger.info(f'{status} {context.path}')
            if do_build or 'dryrun' in status:
                # sort portions of context for better logger output
                context_dict = context.to_dict()
                context_dict.get('dependencies_built', []).sort(key=lambda x: x.get('target'))
                logger.info({'context': context_dict}, submessage=True)
                if self._print_prompt:
                    logger.info('prompt: |', submessage=True)
                    logger.info(context.prompt['prompt'], submessage=True)

            # assign context to new state
            if do_build:
                self._set_context_state(context, 'build_required')
            else:
                if os.path.exists(context.path):
                    self._set_context_state(context, 'built')
                    for postreq in context.config.get('postreqs', []):
                        self.add_target(postreq)
                else:
                    self._set_context_state(context, 'notbuilt')
        self.contexts['buildable'] = set()

    def process_all_build_required(self):
        logger.debug('process_all_build_required()')

        async def _build_context(context):
            await context.build()
            assert os.path.exists(context.path)
            self._set_context_state(context, 'built')
            logger.info(f'built {context.path}')
            for postreq in context.config.get('postreqs', []):
                self.add_target(postreq)

        num_contexts = len(self.contexts['build_required'])
        if num_contexts == 1:
            logger.info('building 1 context')
        elif num_contexts > 1:
            logger.info(f'building {num_contexts} contexts with max_workers={self._max_workers}')

        with logger.make_subtree():
            # NOTE:
            # we have a parallel and non-parallel implementation of this function;
            # both versions should do the exact same thing;
            # the non-parallel version is simpler (and so easier to understand),
            # and also cannot have race conditions;
            # it is generally slower,
            # but is useful for debugging to ensure that the parallel version is correct
            if not self._parallel_build:
                build_required0 = self.contexts['build_required']
                for context in build_required0:
                    self.loop.run_until_complete(_build_context(context))
                self.contexts['build_required'] = set()

            else:
                sem = asyncio.Semaphore(self._max_workers)
                async def limited(context):
                    async with sem:
                        return await _build_context(context)
                async def run_all():
                    tasks = [limited(ctx) for ctx in self.contexts['build_required']]
                    await asyncio.gather(*tasks)
                self.loop.run_until_complete(run_all())
                self.contexts['build_required'] = set()

    def process_all_dependencies(self):
        contexts = self.contexts['unresolved']
        self.contexts['unresolved'] = set()
        logger.debug('process_all_dependencies()')
        with logger.make_subtree():
          for context in contexts:
            logger.debug({'context': context.to_dict()})
            with logger.make_subtree():
                dependencies_unresolved1 = []
                dependencies_building1 = list(context.dependencies_building)
                for dep in context.dependencies_unresolved:
                    logger.debug(f"dep['target']={dep['target']}")

                    # if the dependency requires variables that are unresolved,
                    # we readd it to the state machine to be processed later
                    dep_vars = extract_variables(dep['target'])
                    variables_still_needed = [
                            var for var in context.variables_unresolved if var in dep_vars
                            ]
                    if len(variables_still_needed) > 0:
                        dependencies_unresolved1.append(dep)
                        continue

                    # now we actually resolve the dependency
                    # NOTE:
                    # if variables_resolved contains empty strings,
                    # then no targets will match the dependency and we are done processing this context
                    # if variables_resolved contains newlines,
                    # then the target will be split into multiple targets,
                    # and each of the resulting targets will create a new context
                    targets_withvars = substitute_variables(
                            dep['target'],
                            context.variables_resolved,
                            )
                    for target_withvars in targets_withvars:
                        # we might still get more than one match here;
                        # this can happen (e.g.) if the target contains '**'
                        matches = match_pattern_starstar(
                                self.targets_dict,
                                target_withvars,
                                )

                        # if we don't find a match,
                        # then the target is not defined in the config;
                        # this means that target file cannot be automatically built
                        # but must be provided already by the user;
                        # we will not actually build this file,
                        # but we should still add it to matches and track it like it will be built
                        # so that it gets properly recorded as a dependency
                        if len(matches) == 0:
                            matches = [(target_withvars, {})]

                        for normalized_target, target_env in matches:
                            # construct the new variables_resolved;
                            # transitively substitute variables,
                            # and delete any variables that are not need for the target
                            target_variables = extract_variables(normalized_target)
                            variables_resolved = variables_transitive_substitute({
                                **context.variables_resolved,
                                **target_env,
                                })
                            for var in dict(variables_resolved):
                                assert '$' not in variables_resolved[var]
                                if var not in target_variables:
                                    del variables_resolved[var]

                            # construct the new *_unresolved variables
                            if normalized_target in self.targets_dict:
                                dependencies_unresolved = self.targets_dict[normalized_target]['dependencies']
                                variables_unresolved = dict(self.targets_dict[normalized_target]['variables'])
                                for var in variables_resolved:
                                    if var in variables_unresolved:
                                        del variables_unresolved[var]
                            else:
                                dependencies_unresolved = []
                                variables_unresolved = {}

                            # build the context
                            context1 = BuildContext(
                                    normalized_target=normalized_target,
                                    config=self.targets_dict.get(normalized_target, {}),
                                    variables_resolved=variables_resolved,
                                    variables_unresolved=variables_unresolved,
                                    dependencies_built=[],
                                    dependencies_building=[],
                                    dependencies_unresolved=dependencies_unresolved,
                                    mode=context.dependencies_mode(),
                                    )
                            self._add_context(context1, required_for=context, force_add=context1==context)

                            dep_paths = substitute_variables(normalized_target, target_env)
                            # If any variable in target_env is empty,
                            # then substitute_variables will return [];
                            # This should never happen at this point.
                            assert len(dep_paths) > 0

                            # we need to insert copies of dep with the target modified;
                            # these copies are important to ensure that the non-target
                            # keys in dep are preserved (like input, or is_prompt)
                            for dep_path in dep_paths:
                                dep1 = dict(dep)
                                dep1['target'] = dep_path
                                dependencies_building1.append(freeze(dep1))

                # re-add original context with modified dependencies
                context1 = context.model_copy(update={
                    'dependencies_building': frozenset(dependencies_building1),
                    'dependencies_unresolved': frozenset(dependencies_unresolved1),
                    })
                force_add = context1 == context
                self._add_context(
                    context1,
                    required_for=context,
                    force_add=force_add,
                    )

    def process_all_variable(self):

        contexts = self.contexts['unresolved']
        self.contexts['unresolved'] = set()
        for context in contexts:
            # do not process contexts that still require dependencies to be built
            if len(context.dependencies_building) > 0:
                self._set_context_state(context, 'unresolved')
                continue

            # do not process contexts that do not need more variables built
            if len(context.variables_unresolved) == 0:
                self._set_context_state(context, 'unresolved')
                continue

            # do not process if dependencies not yet built
            # NOTE:
            # we use a janky system to track dependencies of variables that has two key parts:
            # 1) the variables are guaranteed to appear in "sorted" order;
            #    so the next variable is guaranteed not to depend on any subsequent vars
            # 2) if a variable requires one of the dependencies to already be built,
            #    it must contain the dependency string exactly inside of it
            # if either of these two conditions are met,
            # we are not ready to process the context and so we re-add it
            # FIXME:
            # there's lots of non-intuitive behavior here;
            # at the very least, it needs better documentation;
            # I think it is likely possible to construct a fac.yaml that will lead to cyclcal dependencies,
            # and we should figure out a way to check for for those
            var, expr = next(iter(context.variables_unresolved.items()))
            has_dependencies = True
            for dep in context.dependencies_unresolved:
                if dep['target'] in expr:
                    has_dependencies = False
            if not has_dependencies:
                self._add_context(context, required_for=context, force_add=True)
                continue

            # actually evaluate the variable
            value = eval_var(
                expr,
                context.variables_resolved,
                var,
                context.normalized_target,
                self.targets_dict
                )

            # create new dictionaries for the resolved/unresolved variables;
            # then transfer the variable from unresolved to resolved;
            # note that we convert from frozendict to dict (making a copy)
            # so that we can edit the entries
            variables_resolved1 = dict(context.variables_resolved)
            variables_resolved1[var] = value

            variables_unresolved1 = dict(context.variables_unresolved)
            del variables_unresolved1[var]

            context1 = context.model_copy(update={
                'variables_resolved': variables_resolved1,
                'variables_unresolved': variables_unresolved1,
                })
            force_add = context1 == context
            self._add_context(
                context1,
                required_for=context,
                force_add=force_add,
                )
