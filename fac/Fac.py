# stdlib imports
from collections import defaultdict
from typing import Any, Literal
import asyncio
import glob
import itertools
import subprocess
import threading
import time

# external imports
from deepdiff import DeepDiff
from fastapi import FastAPI, APIRouter
from frozendict import frozendict
import git
import uvicorn
import yaml

# project imports
from fac.BuildContext import *
from fac.Config import *
from fac.Errors import *
from fac.FileManager import FileManager
from fac.io_utils import *
from fac.util.FastAPI import *
from fac.util.PrioritySet import PrioritySet
from fac.util.collapse import *
from fac.util.freeze import *
from fac.util.targets import *
from fac.util.templates import *

# setup logging
from fac.Logging import *
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)


class Job:
    '''
    Multiple jobs can be run sequentially or concurrently in BuildState.
    This class tracks which paths/contexts correspond to which build jobs.
    The main purpose of tracking is so we can commit all modified files at once and with an appropriate commit message.
    '''
    job_count = 0

    def __init__(self, build_cmd, repo, auto_commit=True):
        self.build_cmd = build_cmd
        self.repo = repo
        self.auto_commit = auto_commit
        self.contexts = set()
        self.paths = set()
        self.start_time = time.time()
        self.end_time = None
        self.job_id = Job.job_count
        Job.job_count += 1

    def register_context(self, context):
        self.contexts.add(context)
        if context.path_safe():
            self.paths.add(context.path_safe())

    def assert_invariants_finalizable(self):
        # ensure finalize has not already been called
        assert self.end_time is None

        # ensure that all contexts have corresponding built paths
        for context in self.contexts:
            if context.path_safe() and context.mode != 'dryrun':
                assert context.path_safe() in self.paths

    def finalize(self):
        '''
        This method is called after all paths are finally built.
        The main purpose is to commit all built paths to git.
        '''
        self.assert_invariants_finalizable()

        self.end_time = time.time()

        # add/commit the built targets
        def try_add(path):
            try:
                self.repo.git.add(path)
            except git.exc.GitCommandError:
                pass
        if self.auto_commit:
            try_add('fac.yaml')
            try_add('.fac.jsonl')
            for path in self.paths:
                dirname = os.path.dirname(path)
                filename = os.path.basename(path)
                try_add(path)
                try_add(f'./{dirname}/.{filename}.facjson')
                try_add(f'./{dirname}/.{filename}.fac.log')
            commit_message=f'[bot] {self.build_cmd}'

            # the if condition below checks if we actually added files;
            # we only commit if files were actually added;
            # otherwise a large ugly warning will appear
            if self.repo.index.diff('HEAD'):
                self.repo.git.commit('-m', commit_message)


class BuildState(Routable):
    '''
    The build system should be thought of like a state machine,
    where the contexts* attributes represent the different states a context can be in.
    The main work of this class is done in the process_* methods,
    which process the contexts in the corresponding state.
    '''
    def __init__(self, config_file='fac.yaml', allow_dirty=False, auto_commit=True):
        super().__init__()

        # ensure sane git environment
        self.repo = git.Repo('.')
        self.auto_commit = auto_commit
        if auto_commit == False:
            allow_dirty = True
        self.allow_dirty = allow_dirty
        if self.repo.working_dir != os.getcwd():
            logger.error('must be in root of git repo')
            raise DirtyRepo()
        if self.repo.is_dirty(untracked_files=True):
            if allow_dirty:
                logger.warning('git repo is dirty but proceeding with --allow_dirty')
            else:
                logger.error('git repo is dirty')
                logger.error('you can clean the repo by committing all changes', submessage=True)
                logger.error('you can clean the repo by deleting all changes with `git checkout . && git clean -fd`', submessage=True)
                logger.error('you can allow running with a dirty repo using --allow_dirty or --auto_commit=False', submessage=True)
            raise DirtyRepo()

        # create important variables
        self.targets_dict = load_config(config_file)
        self.file_manager = FileManager(self.targets_dict)

        # FIXME:
        # we need our own dedicated event loop here because
        # we are mixing async/sync code;
        # eventually we should move the whole interface to async to fix this wart
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # the states
        self.contexts_unresolved = set()
        self.contexts_buildable = PrioritySet(priority_func=lambda x: x.build_priority())
        self.contexts_waiting = set()
        self.contexts_built = set()
        self.contexts_notbuilt = set()

        # store the full dependency graph of BuildContext instances
        # keys: a BuildContext
        # values: a list of BuildContext instances that require the key
        self.required_for = defaultdict(lambda: [])

        # the jobs
        self.jobs_running: list[Job] = []
        self.jobs_finalized: list[Job] = []
        self.context_to_job = {}
        self.path_to_job = {}

    @route('/list_targets', ['GET'], response_model=dict[str, Any])
    def list_targets(self):
        '''
        Returns a dictionary of targets defined in the 'fac.yaml' file.
        The keys are targets and values are config information describing how to build the targets.

        ---

        A target is a string that may contain shell-like variables
        that describes a formula for generating paths.

        For example:

        1. The target "example.json" contains no variables and will always resolve to path "example.json".

        2. The target "chapters/$CHAPTER/outline.json" with CHAPTER=['0001', '0002', '0003']
            will resolve to the three paths:
            - 'chapters/0001/outline.json'
            - 'chapters/0002/outline.json'
            - 'chapters/0003/outline.json'

        The web API exposes methods for working with targets and their corresponding paths,
        but does not expose an interface for working with the variables.
        The variable definitions are exposed in the config values returned by this endpoint for debug purposes,
        but they are processed internally by the webserver and shouldn't be used in the web app.
        Any web applications must be built to handle arbitrary paths existing for each target.
        '''
        return self.targets_dict

    ########################################
    # sanity checking
    ########################################

    def assert_invariants(self):
        # no context can be in more than one state
        states = [
                self.contexts_unresolved,
                set(self.contexts_buildable.to_list_nopriority()),
                self.contexts_waiting,
                self.contexts_built,
                ]
        for i, state in enumerate(states):
            # this mildly fancy code maintains the O(1) lookup performance for sets
            # this fanciness is needed for the assert checks to run in reasonable time
            # more naive solutions are quadratic,
            # but this solutions is linear runtime
            states_minus_i = set().union(*(s for j, s in enumerate(states) if j != i))
            for context in state:
                assert context not in states_minus_i

        # every built_path has a corresponding context
        # (and vice versa)
        context_paths = set([context.path for context in self.contexts_built])
        assert context_paths == set(self.file_manager.get_fresh_paths())

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
            'contexts_unresolved': f(self.contexts_unresolved),
            'contexts_buildable': f(self.contexts_buildable.to_list()),
            'contexts_waiting': f(self.contexts_waiting),
            'contexts_built': f(self.contexts_built),
            'contexts_notbuilt': f(self.contexts_notbuilt),
            }

    def debug_short(self, submessage=False):
        logger.debug({'BuildState': {
            'len(self.contexts_unresolved)': len(self.contexts_unresolved),
            'len(self.contexts_buildable)': len(self.contexts_buildable.to_list()),
            'len(self.contexts_waiting)': len(self.contexts_waiting),
            'len(self.contexts_built)': len(self.contexts_built),
            }}, submessage=submessage)

    def _state_as_dict(self, longform=True):
        '''
        Convert the internal state into dictionary suitable for yaml conversion.
        Return a deepcopy so that the returned value does not get modified as future processing happens.
        '''
        if longform:
            yaml_dict = {
                'buildable(long)': [context.to_dict() for priority, context in self.contexts_buildable.to_list()],
                'waiting(long)': [context.to_dict() for context in self.contexts_waiting],
                'unresolved(long)': [context.to_dict() for  context in self.contexts_unresolved],
                }
        else:
            yaml_dict = {
                'buildable': sorted([context.denormalized_target() for priority, context in self.contexts_buildable.to_list()]),
                'waiting': sorted([context.denormalized_target() for context in self.contexts_waiting]),
                'unresolved': sorted([context.denormalized_target() for  context in self.contexts_unresolved]),
                }
        return copy.deepcopy(yaml_dict)

    def debug_statediff(self, state0, msg_str=''):
        state1 = self._state_as_dict()
        text0 = yaml.dump(state0, default_flow_style=False, sort_keys=False)
        text1 = yaml.dump(state1, default_flow_style=False, sort_keys=False)
        import difflib
        diff = difflib.unified_diff(
                text0.splitlines(keepends=True),
                text1.splitlines(keepends=True),
                )
        print(''.join(diff))
        return

        diff = DeepDiff(state0, state1, verbose_level=2)
        
        # ensure that the diff only has keys we recognize
        for k in diff:
            assert k in ['values_changed', 'iterable_item_added', 'iterable_item_removed']

        # print output
        print(10 * '-')
        print(f'|| BuildState diff {msg_str} ||')
        print(10 * '-')
        output = {}
        states = ['buildable', 'waiting', 'unresolved']
        for state in states:
            print(f'{state} (diff)')
            for k in diff.get('iterable_item_removed', []):
                print(f'< {diff["iterable_item_removed"][k]}')
            for k in diff.get('iterable_item_added', []):
                print(f'> {diff["iterable_item_added"][k]}')
            for k in diff.get('values_changed', []):
                print(f'< {diff["values_changed"][k]["old_value"]}')
                print(f'> {diff["values_changed"][k]["new_value"]}')

        return state1

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

    def _state_hash(self):
        '''
        Compute a hash of the states.
        This is a debug utility function.
        It is used to ensure that we do not get stuck in an infinite loop processing a cycle of states.

        NOTE:
        We do not implmement __hash__ because this object is mutable and not hashable.
        '''
        states = [
            self.contexts_built,
            self.contexts_buildable,
            self.contexts_waiting,
            self.contexts_unresolved,
            ]
        return hash(freeze(states))

    ########################################
    # build files
    ########################################

    def build_daemon(self):
        '''
        Creates a daemon thread that will continuously build any targets added with `add_target`.
        This method is used by facd to ensure that the /add_target endpoint results in builds.

        FIXME:
        It is not safe to run build_all manually after build_daemon has been called.
        We should probably add a lock to the build_all function to prevent this from happening.
        '''
        # to make this method idempotent,
        # we will store the daemon thread as an attribute;
        # then we only create the daemon thread if this attr doesn't exist
        if hasattr(self, '_daemon_thread') and self._daemon_thread.is_alive():
            return self._daemon_thread

        def daemon_loop():
            while True:
                self.build_all()
                time.sleep(1)
        self._daemon_thread = threading.Thread(target=daemon_loop, daemon=True)
        self._daemon_thread.start()
        return self._daemon_thread

    def build_all(self):
        with logger.make_subtree():
            # states will store a hash of BuildState at every iteration;
            # we will use this set to ensure that we don't get stuck in an infinite loop
            # repeating the same cycle of states forever;
            # in theory, this should not be needed,
            # and it is a sanity debug check to ensure our state transitions work correctly
            states = set()
            #self.debug_print(f'iter={len(states)}')
            while not self.is_done():
                state0 = self._state_as_dict()

                # perform all state transitions
                self.process_all_dependencies()
                #state0 = self.debug_statediff(state0, f'iter={len(states)} -- deps')
                #self.debug_print(f'iter={len(states)} -- deps')
                self.assert_invariants()
                self.debug_short()
                self.process_all_buildable()
                #state0 = self.debug_statediff(state0, f'iter={len(states)} -- build')
                #self.debug_print(f'iter={len(states)} -- build')
                self.assert_invariants()
                self.process_all_variable()
                #state0 = self.debug_statediff(state0, f'iter={len(states)} -- vars')
                #self.debug_print(f'iter={len(states)} -- vars')
                self.assert_invariants()
                #self.debug_print(f'iter={len(states) + 1}')

                self._finalize_jobs()

                # sanity infinite loop check
                state = self._state_hash()
                if state in states:
                    all_dryrun = True
                    for context in itertools.chain(
                            self.contexts_buildable.to_list_nopriority(),
                            self.contexts_waiting,
                            self.contexts_unresolved,
                            ):
                        if context.mode != 'dryrun':
                            all_dryrun = False
                    if not all_dryrun:
                        logger.error('duplicate state detected --- this is a bug in fac')
                    else:
                        pass
                        #logger.warning('evaluated as far as dryrun will allow')
                        #logger.warning(self.get_states(show_len=True), submessage=True)
                    break
                states.add(state)

    def is_done(self):
        return not any([
            len(self.contexts_unresolved) > 0,
            len(self.contexts_buildable) > 0,
            len(self.contexts_waiting) > 0,
            ])

    ########################################
    # state transition methods
    ########################################

    def full_dryrun(self, build_all=True):
        '''
        Perform a dryrun on all targets in the fac.yaml.
        The dryrun lets fac know which files are already built.
        '''
        #for target in self.targets_dict:
            #self.add_target(target, mode='dryrun')
        self.add_target('**', mode='dryrun')
        if build_all:
            self.build_all()

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
        - target (str): the target to be built; all variables must be specified; suppo
   globstar (**)-style pattern matching
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
            job = Job(build_cmd, self.repo, auto_commit=self.auto_commit)
            self.jobs_running.append(job)
        else:
            job = self.context_to_job[context]

        # create the contexts
        for normalized_target, target_env in matches:

            # variables_unresolved starts off the config,
            # but we pre-resolve every variable in target_env
            variables_unresolved = dict(copy.deepcopy(self.targets_dict[normalized_target]['variables']))
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
        def maybe_add(queue):
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
            if not force_add and (queue, context) in self._contexts_history:
                return
            self._contexts_history.add((queue, context))
            if queue == 'waiting':
                self.contexts_waiting.add(context)
            elif queue == 'buildable':
                self.contexts_buildable.add(context)
            elif queue == 'unresolved':
                self.contexts_unresolved.add(context)
            else:
                assert False

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
            if context in self.contexts_built:
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

            # if the context has been resolved to a path,
            # register it as queued
            path = context.path_safe()
            if path and context.mode != 'dryrun':
                self.file_manager.add(path, 'queued')

    def _finalize_jobs(self):
        states = [
                self.contexts_unresolved,
                set(self.contexts_buildable.to_list_nopriority()),
                self.contexts_waiting,
                ]
        jobs_running = self.jobs_running
        self.jobs_running = []
        for job in jobs_running:
            done = True
            for context in job.contexts:
                for state in states:
                    if context in state:
                        done = False
            if done:
                logger.info(f'finalizing job {job.job_id}')
                job.finalize()
                self.jobs_finalized.append(job)
            else:
                self.jobs_running.append(job)

    def process_all_waiting(self):
        logger.debug(f'process_all_waiting()')
        self.debug_short(submessage=True)
        waiting0 = self.contexts_waiting
        self.contexts_waiting = set()
        for context in waiting0:
            self.process_waiting(context, waiting0)
        self.debug_short(submessage=True)

    @with_subtree(logger)
    def process_waiting(self, context, waiting0):
        logger.debug(f'process_waiting()')
        logger.debug({'context': context.to_dict()}, submessage=True)
        dependencies_built1 = list(context.dependencies_built)
        dependencies_building1 = []
        for dep in context.dependencies_building:
            denormalized_targets = substitute_variables(dep['target'], context.variables_resolved)
            for denormalized_target in denormalized_targets:
                # denormalized_target is a path whenever it does not contain '$';
                # paths and targets must be handled differently
                if '$' not in denormalized_target:
                    path = denormalized_target
                    if path in self.file_manager.get_fresh_paths():
                        dep1 = dict(dep)
                        dep1['target'] = path
                        dependencies_built1.append(dep1)
                    else:
                        dependencies_building1.append(dep)

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
                            self.contexts_unresolved,
                            self.contexts_buildable.to_list_nopriority(),
                            self.contexts_waiting,
                            waiting0,
                            ):
                        if denormalized_target == loop_context.normalized_target and loop_context != context:
                            all_targets_built = False
                    if not all_targets_built:
                        dependencies_building1.append(dep)
                    else:
                        dep_targets = freeze([dep['target'] for dep in context.config['dependencies']])
                        for loop_context in self.contexts_built:
                            dep1 = dict(copy.deepcopy(dep))
                            dep1['target'] = loop_context.path
                            matches = match_pattern_starstar(dep_targets, dep1['target'])
                            if len(matches) == 1:
                                # FIXME:
                                # the if statement is needed for when fac builds more than one target at a time
                                # (either through demon mode or multiple cmd line args)
                                # in that case, contexts_built will contain paths that do not necessarily correspond to the current context,
                                # and the if statement ensures that only those paths for this context will be added;
                                # the problem (and thing to fix) is that the match_pattern_starstar function is slow
                                # and should not be in an inner loop
                                dependencies_built1.append(freeze(dep1))
                            assert '$' not in dep1['target']
        context1 = context.model_copy(update={
            'dependencies_built': dependencies_built1,
            'dependencies_building': dependencies_building1,
            })
        self._add_context(context1, required_for=context, force_add=context1==context)

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

    async def _maybe_build_context(self, context):
        '''
        Build a single context if needed.

        NOTE:
        The difference between this function and BuildContext.build is:
        - this function only builds when needed
        - this function updates self.file_manager
        - this function handles postreqs
          (It doesn't build them directly, but adds them to the build system.
          This ensures that any additional var/dep process get processed,
          and that the build is scheduled properly.)
        '''
        status, do_build = context.get_status()
        logger.info(f'{status} {context.path}')
        #required_for = self.trace_required_for(context)
        #logger.info({'required_for': flatten_singletons(required_for)}, submessage=True)
        if context.normalized_target not in self.targets_dict:
            logger.warning(f'target {context.normalized_target} not in self.target_dicts, cannot build', submessage=True)
        else:
            #logger.info(f'hash: {hash(context)}', submessage=True)
            if do_build:

                # sort portions of context for better logger output
                context_dict = context.to_dict()
                context_dict.get('dependencies_built', []).sort(key=lambda x: x.get('target'))
                logger.info({'context': context_dict}, submessage=True)

                # build context
                self.file_manager.add(context.path, status='building')
                await context.build()

        if os.path.exists(context.path):
            self.contexts_built.add(context)
            self.file_manager.add(context.path, status='fresh')

        for postreq in context.config.get('postreqs', []):
            self.add_target(postreq)

    def process_all_buildable(self, max_workers=20, threaded_build=False):
        logger.debug(f'process_all_buildable()')
        self.assert_invariants()
        self.process_all_waiting()
        self.assert_invariants()

        # NOTE:
        # we have a threaded and non-threaded implementation of this function;
        # both versions should do the exact same thing;
        # the non-threaded version is simpler (and so easier to understand),
        # and also cannot have race conditions;
        # it is generally slower because it cannot process builds in parallel,
        # but is useful for debugging to ensure that the threaded version is correct
        if not threaded_build:
            while len(self.contexts_buildable) > 0:
                context = self.contexts_buildable.pop()
                self.loop.run_until_complete(self._maybe_build_context(context))
                self.assert_invariants()
                self.process_all_waiting()
                self.assert_invariants()

        else:
            '''
            from concurrent.futures import ThreadPoolExecutor, as_completed

            # run all build tasks in parallel
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                while len(self.contexts_buildable) > 0:
                    context = self.contexts_buildable.pop()
                    future = executor.submit(asyncio.run, self._maybe_build_context(context))
                    futures.append(future)
                executor.shutdown()

            # once all threads have terminated, we raise any exceptions;
            # if multiple threads raise exceptions, we should see them all;
            # we allow all threads to finish running and only display errors
            # after non-erroring threads terminate
            # (API calls typically bill at the start of the call,
            # and so this ensures that we do not "waste" the money from an API call
            # by needlessly discarding the results)
            exceptions = []
            for future in futures:
                try:
                    future.result()
                except Exception as e:
                    exceptions.append(e)
            if exceptions:
                raise ExceptionGroup("Exceptions in build threads", exceptions)
            '''
            # FIXME:
            # the code above doesn't work correctly;
            # the code below is a bit more idiomatic,
            # but still might have bugs;
            # there's still a lot more work to do to make the async code "nice"
            sem = asyncio.Semaphore(max_workers)
            async def limited(context):
                async with sem:
                    return await self._maybe_build_context(context)
            async def run_all():
                tasks = [limited(ctx) for ctx in self.contexts_buildable.to_list_nopriority()]
                await asyncio.gather(*tasks)
            self.loop.run_until_complete(run_all())

            # assert all invariants hold
            self.assert_invariants()
            self.process_all_waiting()
            self.assert_invariants()

    def process_all_dependencies(self):
        contexts = self.contexts_unresolved
        self.contexts_unresolved = set()
        logger.debug(f'process_all_dependencies()')
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
                                variables_unresolved = dict(copy.deepcopy(self.targets_dict[normalized_target]['variables']))
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
                            dependencies_building1.extend([
                                frozendict({'target': dep_path}) for dep_path in dep_paths
                                ])

                # re-add original context with modified dependencies
                context1 = context.model_copy(update={
                    'dependencies_building': frozenset(dependencies_building1),
                    'dependencies_unresolved': frozenset(dependencies_unresolved1),
                    })
                self._add_context(context1, required_for=context, force_add=context1==context)

    def process_all_variable(self):

        contexts = self.contexts_unresolved
        self.contexts_unresolved = set()
        for context in contexts:
            # do not process contexts that still require dependencies to be built
            if len(context.dependencies_building) > 0:
                self.contexts_unresolved.add(context)
                continue

            # do not process contexts that do not need more variables built
            if len(context.variables_unresolved) == 0:
                self.contexts_unresolved.add(context)
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
            try:
                value = eval_var(
                        var,
                        expr,
                        context.variables_resolved,
                        )
            except VariableEvaluationError as e:
                logger.error(f'Error evaluating variable {var} in target {context.normalized_target}')

                # print hints for how to resolve common errors
                patterns = [
                    r"jq: error: Could not open file (.+?):",
                    r"ls: cannot access '(.+?)':",
                ]
                for pattern in patterns:
                    match = re.search(pattern, e.cmd.stderr)
                    if match:
                        path = match.group(1)
                        target_matches = match_pattern_starstar(self.targets_dict, path)
                        logger.error(f'HINT: {var} depends on file {path}')
                        if len(target_matches) == 0:
                            logger.error('HINT: there are no targets that correspond to this path')
                        else:
                            logger.error(f'HINT: add "{target_matches[0][0]}" to the dependencies to build the file')

                # print raw output
                logger.error('stderr: |', submessage=True)
                for line in (e.cmd.stderr.strip()).strip().split('\n'):
                    logger.error('  ' + line, submessage=True)
                if len(e.cmd.stdout.strip()) > 0:
                    logger.error('stdout: |', submessage=True)
                    for line in (e.cmd.stdout).strip().split('\n'):
                        logger.error('  ' + line, submessage=True)
                logger.error({'context': context.to_dict()}, submessage=True)
                raise e

            # create new dictionaries for the resolved/unresolved variables;
            # then transfer the variable from unresolved to resolved;
            # note that we convert from frozendict to dict (making a copy)
            # so that we can edit the entries
            variables_resolved1 = dict(context.variables_resolved)
            variables_resolved1[var] = value

            variables_unresolved1 = dict(context.variables_unresolved)
            del variables_unresolved1[var]

            context1 = BuildContext(
                    normalized_target=context.normalized_target,
                    config=context.config,
                    variables_resolved=variables_resolved1,
                    variables_unresolved=variables_unresolved1,
                    dependencies_built=context.dependencies_built,
                    dependencies_building=context.dependencies_building,
                    dependencies_unresolved=context.dependencies_unresolved,
                    include_prompt=context.include_prompt,
                    include_old=context.include_old,
                    include_paths=context.include_paths,
                    mode=context.mode,
                    )
            self._add_context(context1, required_for=context, force_add=context1==context)


################################################################################

from functools import lru_cache
@lru_cache()
def eval_var(var, expr, env):
    '''
    Evaluate the bash expression with the given environment variables.
    Note that this is operation is more than just variable expansion,
    but actually invokes a bash subshell.

    NOTE:
    These subshells are moderately expensive,
    and so we use an lru_cache to speed up processing.
    This requires that expr be idempotent and side-effect free to maintain correctness.
    It's not obvious that the performance gains are really worth this restriction.

    >>> eval_var('var', 'echo "hello $NAME"', frozendict({'NAME': 'world'}))
    'hello world'
    '''
    # log the effictiveness of the cache;
    # this will only get printed on cache-misses
    logger.debug(f'eval_var.cache_info()={eval_var.cache_info()}')

    # evaluate expr in bash
    full_command = "set -eu; " + expr.strip()
    cmd = subprocess.run(
        full_command,
        shell=True,
        capture_output=True,
        text=True,
        executable="/bin/bash",
        env=env,
        )
    if cmd.returncode != 0:
        raise VariableEvaluationError(var, expr, env, cmd)
    stdout = cmd.stdout.strip()

    # if val is an integer, pad it with zeros
    lines = []
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            try:
                # zero pad integers before adding to list
                intval = int(line)
                line = f'{intval:04d}'
            except ValueError:
                pass
            lines.append(line)

    result = '\n'.join(lines)
    return result


class VariableEvaluationError(FACError):
    def __init__(self, var, expr, context, result):
        self.cmd = result
        errorstrs = [
            f'error evaluating {var}=$({expr})',
            f'context={context}',
            f"result.returncode={result.returncode}",
            f"result.stdout={result.stdout}",
            f"result.stderr={result.stderr}",
            ]
        super().__init__('\n'.join(errorstrs))

