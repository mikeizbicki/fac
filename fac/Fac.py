# stdlib imports
from collections import defaultdict
import asyncio
import itertools
import os

# external imports
import yaml
from watchfiles import awatch, Change

# project imports
from fac.BuildContext import BuildContext, context_print
from fac.Config import load_config
from fac.Errors import DirtyRepo, FACError
from fac.PathRoutes import PathRoutes
from fac.Job import Job, assert_git_sane
from fac.io_utils import FacJSON
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
        self._max_workers = 20
        self._parallel_build = True
        self._do_assert_invariants = True
        self._do_merge_contexts = True
        self._print_prompt = print_prompt
        self._print_states_when_building = False
        self._shutdown = False

        # create important variables
        self.targets_dict = load_config(config_file)

        # the states
        #
        # WARNING:
        # the order of these states defines their semantic precedence
        # when merging two states; this is probably more fragile
        # than it should be
        self.contexts = {
            'stale': set(),
            'notbuilt': set(),
            'unresolved': set(),
            'waiting': set(),
            'phantom': set(),
            'buildable': set(),
            'build_required': set(),
            'built': set(),
        }
        self.path2context = {}
        self.path_routes = PathRoutes(self.targets_dict)
        self._contexts_history = defaultdict(lambda: [])

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

    def add_target(
            self,
            target: str,
            required_for=None,
            include_prompt=None,
            include_old=False,
            include_paths=None,
            tasks={'build'},
            ):
        '''
        Register a target with the build system.
        '''
        matches = match_pattern_starstar(self.targets_dict, target)

        if len(matches) == 0:
            logger.error(f'target {target} has no match in fac.yaml')
            raise FACError()

        # get job info
        if required_for is None:
            str_mode = ''
            if 'overwrite' in tasks:
                str_mode = ' --overwrite'
            if len(tasks) == 0:
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
                    tasks=tasks,
                    )
            self._add_context(context, required_for=required_for, force_add=False, job=job)

    async def build_daemon(self):
        loop = asyncio.get_event_loop()
        watch_task = loop.create_task(self._watch_files())
        try:
            while True:
                # Run sync build_all in executor so it doesn't block the event loop
                await loop.run_in_executor(None, self.build_all)
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self._shutdown = True
            logger.warning('build_daemon cancelled')
        finally:
            watch_task.cancel()
            try:
                await watch_task
            except asyncio.CancelledError:
                pass

    def build_all(self):
        # FIXME:
        # we need our own dedicated event loop here because
        # we are mixing async/sync code;
        # eventually we should move the whole interface to async to fix this wart
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.async_build_all())

    async def async_build_all(self):
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
                    ]) and not self._shutdown:

                state0 = state_hash()
                state1 = None

                # perform all context state transitions
                while state0 != state1 and not self._shutdown:
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

                await self.process_all_build_required()
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
                        if len(context.tasks) > 0:
                            all_dryrun = False
                    if not all_dryrun:
                        logger.error('duplicate state detected --- this is a bug in fac')
                    else:
                        pass
                        # FIXME:
                        # it would be nice to log this event,
                        # but it currently happens too often;
                        # we need to make it happen only once
                        #logger.info('evaluated as far as dryrun will allow')
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

    @route('/job_states', ['GET'])
    def job_states(self, format='len'):
        if format == 'full':
            return self.jobs
        elif format == 'len':
            return {state: len(self.jobs[state]) for state in self.jobs}
        else:
            raise ValueError('invalid format')

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

    def add_jobs_callback(self, f):
        self.jobs_callbacks.append(f)

    def run_jobs_callbacks(self):
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
                if context in self.contexts['waiting'] and len(context.tasks) > 0:
                    done = False
            if done:
                logger.info(f'finalizing job {job.job_id}')
                job.finalize()
                self.jobs['succeeded'].add(job)
                self.run_jobs_callbacks()
            else:
                self.jobs['running'].add(job)
        self.assert_invariants_jobs()

    ########################################
    # sanity checking
    ########################################

    def assert_invariants(self):
        # these checks are VERY slow
        if False:
            # every context in 'built' has a good status
            for context in self.contexts['built']:
                status, do_build = context.get_status()
                assert not do_build

        if self._do_assert_invariants:
            # no context can be in more than one state
            for state1 in self.contexts.keys():
                for state2 in self.contexts.keys():
                    if state1 != state2:
                        for context in self.contexts[state1]:
                            assert context not in self.contexts[state2], f'state1={state1}, state2={state2}, context.path_safe()={context.path_safe()}'

            # no path can be in more than one context
            #
            # FIXME:
            # We can get two contexts with the same path if
            # two different jobs submit the same path with different parameters
            # (e.g. adding custom prompt, using mode='dryrun' vs 'build).
            # Possible fixes here include:
            # a. Enforcing the invariant at a per-job level.
            # b. Removing old contexts when newer jobs would result in a conflict
            path_states = defaultdict(lambda: [])
            path_contexts = defaultdict(lambda: [])
            for state in self.contexts:
                for context in self.contexts[state]:
                    if context.path_safe():
                        path_states[context.path].append(state)
                        path_contexts[context.path].append(context)
            for path, states in sorted(path_states.items()):
                if len(states) > 1:
                    logger.warning(f'multi_state: path={path} states={states}')
                    #context0 = path_contexts[path][0]
                    #context1 = path_contexts[path][1]
                    #merge_context(context0, context1)
                if self._do_merge_contexts:
                    assert len(states) == 1, f'path={path} states={states}'

            # self.path2context invariants
            for path, context in self.path2context.items():
                assert path == context.path

                # every context is associated with some state
                assert any([context in self.contexts[state] for state in self.contexts]), f"context.path_safe()={context.path_safe()}"

            # every context with a path is in self.path2context
            for state in self.contexts:
                for context in self.contexts[state]:
                    if context.path_safe():
                        assert context.path_safe() in self.path2context

    ########################################
    # file monitoring
    ########################################

    @route('/rdeps', ['GET'])
    def get_rdeps(self, path, recursive=True):
        if not recursive:
            return sorted(self.rdeps[path])

        else:
            result = set()
            stack = [path]
            while stack:
                p = stack.pop()
                for dep in self.rdeps[p]:
                    if dep not in result:
                        result.add(dep)
                        stack.append(dep)
            return sorted(result)


    def update_rdeps_state(self, path):
        for rdep in itertools.chain([path], self.get_rdeps(path)):
            rdep_context = self.path2context[rdep]
            status, do_build = rdep_context.get_status()
            if not os.path.exists(rdep):
                self._set_context_state(rdep_context, 'notbuilt')
            if do_build:
                for state in self.contexts:
                    self.contexts[state].discard(rdep_context)
                if os.path.exists(rdep):
                    self._set_context_state(rdep_context, 'stale')

    async def _watch_files(self):
        async for changes in awatch("."):
            for change_type, abs_path in changes:
                path = os.path.relpath(abs_path)
                if path in self.path2context:
                    logger.warning(f"change_detected ({change_type}): path={path}")
                    self.update_rdeps_state(path)

    ########################################
    # visualize state
    ########################################

    @route('/context_states', ['GET'])
    def context_states(self, format='simple'):
        '''
        Returns the internal state of the build system.
        '''
        if format == 'full':
            return self.contexts
        elif format == 'len':
            return {state: len(self.contexts[state]) for state in self.contexts}
        elif format == 'simple':
            ret = {}
            for state in self.contexts:
                ret[state] = []
                for context in self.contexts[state]:
                    targets = context.denormalized_target()
                    if len(targets) == 1:
                        ret[state].append(targets[0])
                    else:
                        ret[state].append(targets)
                    #if context.path_safe():
                        #ret[state].append(context.path)
                    #else:
                        #ret[state].append(context.normalized_target)
                ret[state].sort()
            return ret
        else:
            return ValueError('unknown format')

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
            yaml_dict = {k: [context.to_dict() for context in contexts] for k, contexts in self.contexts.items()}
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
        # two contexts will be in conflict if they both resolve to the same path;
        # if there are any conflicting conflicts,
        # we merge these contexts and then add the merged context;
        if self._do_merge_contexts:
            if context.path_safe() and context.path in self.path2context:
                oldcontext = self.path2context[context.path]
                for loop_state in self.contexts:
                    if oldcontext in self.contexts[loop_state]:
                        self.contexts[loop_state].remove(oldcontext)
                        context = merge_context(context, oldcontext)
                        self.context_to_job[context] = self.context_to_job[oldcontext]
                        self.context_to_job[context].register_context(context)
                        contexts = list(self.contexts)
                        state = max(loop_state, state, key=lambda x: contexts.index(x))

        self.contexts[state].add(context)
        self._contexts_history[context].append(state)

        if context.path_safe():
            self.path2context[context.path] = context
            for dep in context.dependencies_built:
                self.rdeps[dep['target']].add(context.path)
            self.path_routes.register_context(context, state)

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

        if context != required_for:
            self.required_for[context].append(required_for)

        context_orig = context
        context_splits = context.split()
        if len(context_splits) == 0:
            if context.path_safe():
                logger.warning(f'phantom path: {context.path_safe()}')
                self._set_context_state(context, 'phantom')
            
        for context in context_splits:
            if context_orig.path_safe():
                assert context_orig.path_safe() == context.path_safe()

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
                state = 'waiting'
            else:
                if (len(context.variables_unresolved) == 0 and
                   len(context.dependencies_unresolved) == 0):
                    state = 'buildable'
                else:
                    state = 'unresolved'
            if force_add or state not in self._contexts_history[context]:
                self._set_context_state(context, state)

    def process_all_waiting(self):
        logger.debug('process_all_waiting()')
        self.debug_short(submessage=True)
        waiting0 = self.contexts['waiting']
        self.contexts['waiting'] = set()
        for context in sorted(waiting0, key=lambda x: x.path_safe() or ''):
            self.process_waiting(context, waiting0)
        self.debug_short(submessage=True)
        self.assert_invariants()

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
        force_add = context1 == context
        self._add_context(context1, required_for=context, force_add=force_add)

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

        buildable = self.contexts['buildable']
        self.contexts['buildable'] = set()
        for context in buildable:
            # lock/unlock files
            if 'lock' in context.tasks:
                status = ['lock']
                do_build = False
                facjson = FacJSON(context.path)
                facjson.set('locked', True)
                facjson.save()
            elif 'unlock' in context.tasks:
                status = ['unlock']
                do_build = False
                facjson = FacJSON(context.path)
                facjson.set('locked', False)
                facjson.save()
            else:
                # determine if context needs building
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
                    # FIXME:
                    # context.prompt can have different types :(
                    # this is used to pass in options to image models,
                    # but this feels very bug-prone;
                    # we should make it always be the same
                    try:
                        logger.info(context.prompt['prompt'], submessage=True)
                    except TypeError:
                        logger.info(context.prompt, submessage=True)
            if 'lock' in context.tasks:
                logger.info('lock', submessage=True)
            if 'unlock' in context.tasks:
                logger.info('unlock', submessage=True)

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

    async def process_all_build_required(self):
        logger.debug('process_all_build_required()')

        failures = []

        async def _build_context(context):
            try:
                await context.build()
                assert os.path.exists(context.path)
                logger.info(f'built {context.path}')
                for postreq in context.config.get('postreqs', []):
                    self.add_target(postreq)
                self._set_context_state(context, 'built')
            except Exception as e:
                # if context.build() throws FACError,
                # that means the error was already printed/handled internally;
                # we just register the context as failed;
                # for all other Exceptions,
                # something unexpected happened and we want to see the exception
                if not isinstance (e, FACError):
                    logger.error(f'failed to build {context.path}: {e}')
                self._set_context_state(context, 'notbuilt')
                failures.append((context, e))

        num_contexts = len(self.contexts['build_required'])
        if num_contexts == 1:
            logger.info('building 1 context')
        elif num_contexts > 1:
            logger.info(f'building {num_contexts} contexts with max_workers={self._max_workers}')

        with logger.make_subtree():
            build_required0 = self.contexts['build_required']
            self.contexts['build_required'] = set()
            if not self._parallel_build:
                for context in build_required0:
                    await _build_context(context)

            else:
                sem = asyncio.Semaphore(self._max_workers)
                async def limited(context):
                    async with sem:
                        return await _build_context(context)
                tasks = [limited(ctx) for ctx in build_required0]
                await asyncio.gather(*tasks)

        if failures:
            paths = [ctx.path for ctx, _ in failures]
            logger.error(f'{len(failures)} build(s) failed: {paths}')
            # Re-raise the first exception after all builds complete
            raise failures[0][1]

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
                    # we re-add it to the state machine to be processed later
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
                                #assert '$' not in variables_resolved[var]
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
                                    tasks=context.dependency_tasks(),
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


def safe_dict_union(dict1, dict2):
    """
    Returns the union of two dicts, raising an error if the same key
    has different values in both dicts.

    >>> safe_dict_union({'a': 1, 'b': 2}, {'b': 2, 'c': 3})
    {'a': 1, 'b': 2, 'c': 3}

    >>> safe_dict_union({'x': 10}, {'y': 20, 'z': 30})
    {'x': 10, 'y': 20, 'z': 30}

    >>> safe_dict_union({}, {'a': 1})
    {'a': 1}

    >>> safe_dict_union({'a': 1}, {})
    {'a': 1}

    >>> safe_dict_union({'a': 1, 'b': 2}, {'b': 3, 'c': 3})  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    AssertionError: Conflict: key 'b' has different values: 2 vs 3
    """
    result = dict(dict1)
    for key, value in dict2.items():
        if key in result:
            assert result[key] == value, \
                    f"Conflict: key '{key}' has different values: {result[key]} vs {value}"
        else:
            result[key] = value
    return result


def merge_context(context1, context2, slow_sanity_check=True):
    '''
    Occasionally we create a new BuildContext that "conflicts" with an existing
    context in the sense that they both resolve to the same path.
    This function merges them into a single context.

    It performs a number of integrity checks to ensure that the two contexts
    are compatible with each other and would eventually have resulted in
    the same files(s) getting built after they were both fully resolved.
    Some of these integrity checks are a bit jankier than I'd like them to be.
    
    NOTE:
    I've tried several times getting doctests for this function.
    In principle, it should be possible because this is a "pure" function without IO.
    In practice, the doctests interact with IO due to assert_invariants() checks,
    and so the doctests are too brittle and more trouble than they are worth.
    '''

    # all of the following properties must be identical to merge
    assert context1.normalized_target == context2.normalized_target
    assert context1.config == context2.config
    assert context1.include_prompt == context2.include_prompt
    assert context1.include_old == context2.include_old
    assert context1.include_paths == context2.include_paths

    # we keep all resolved variables from both contexts;
    # we only keep unresolved variables if they are not resolved in the other context
    variables_resolved = safe_dict_union(
            context1.variables_resolved,
            context2.variables_resolved,
            )
    variables_unresolved = safe_dict_union(
            context1.variables_unresolved,
            context2.variables_unresolved,
            )
    for var, expr in list(variables_unresolved.items()):
        if var in variables_resolved:
            if slow_sanity_check:
                # the check enforces that any unresolved variables
                # will resolve to the same value in both contexts;
                # normally it is not safe to evaluate arbitrary variables,
                # and we need a complex set of checks to ensure that
                # appropriate dependencies have already been defined;
                # in this case, however, we know that the variable
                # has already been evaluated once by the other context;
                # so any needed dependencies (i.e. files) should already
                # have been created
                value = eval_var(expr, variables_resolved)
                assert value == variables_resolved[var]
            del variables_unresolved[var]

    # we keep all built dependencies from both contexts
    dependencies_built = context1.dependencies_built | context2.dependencies_built
    built_paths = set([dep['target'] for dep in dependencies_built])

    # processing the other dependencies is rather complicated for two reasons:
    # they are stored in a different format (normalized instead of paths),
    # we only keep building dependencies if they have not already been built
    dependencies_building = set(
            context1.dependencies_building |
            context2.dependencies_building
            )
    for dep in list(dependencies_building):
        denormalized_targets = substitute_variables(
                dep['target'],
                variables_resolved,
                )
        denormalized_targets = substitute_variables(
                dep['target'],
                variables_resolved,
                )
        if len(denormalized_targets) == 0:
            dependencies_building.remove(dep)
        else:
            # either all targets should be built or no targets should be built
            if all([target in built_paths for target in denormalized_targets]):
                dependencies_building.remove(dep)
            else:
                assert all([target not in built_paths for target in denormalized_targets])

    dependencies_unresolved = set(
            context1.dependencies_unresolved |
            context2.dependencies_unresolved
            )
    for dep in list(dependencies_unresolved):
        # if dep has already advanced from unresolved -> building,
        # remove it from unresolved
        if dep in dependencies_building:
            dependencies_unresolved.remove(dep)

        # if dep has already been built,
        # remove it from unresolved
        denormalized_targets = substitute_variables(
                dep['target'],
                variables_resolved,
                )
        if len(denormalized_targets) == 0:
            dependencies_unresolved.remove(dep)
        else:
            if all([target in built_paths for target in denormalized_targets]):
                dependencies_unresolved.remove(dep)
            else:
                assert all([target not in built_paths for target in denormalized_targets])

    return context1.model_copy(update={
        'tasks': context1.tasks | context2.tasks,
        'variables_resolved': variables_resolved,
        'variables_unresolved': variables_unresolved,
        'dependencies_built': dependencies_built,
        'dependencies_building': dependencies_building,
        'dependencies_unresolved': dependencies_unresolved,
        },
        # we don't assert the BuildContext invariants
        # because these check that all paths in dependencies_built actually exist,
        # and that breaks the doctests
        assert_invariants=False,
        )
