# stdlib imports
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal
import asyncio
import glob
import hashlib
import itertools
import subprocess
import threading
import time

# external imports
from deepdiff import DeepDiff
from fastapi import FastAPI, APIRouter
from frozendict import frozendict
from pydantic import BaseModel
import git
import uvicorn
import yaml

# project imports
from fac.Config import *
from fac.Errors import *
from fac.FileManager import FileManager
from fac.LLM import LLM, LLMError
from fac.io_utils import *
from fac.util.FastAPI import *
from fac.util.PrioritySet import PrioritySet
from fac.util.targets import *
from fac.util.templates import *

# setup logging
from fac.Logging import *
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)


def freeze(obj):
    """Recursively convert dicts to frozendicts and iterables to frozensets.

    >>> freeze({'a': 1, 'b': 2})
    frozendict.frozendict({'a': 1, 'b': 2})

    >>> freeze({'nested': {'x': 1}})
    frozendict.frozendict({'nested': frozendict.frozendict({'x': 1})})

    >>> freeze([1, 2, 3])
    frozenset({1, 2, 3})

    >>> freeze({1, 2, 3})
    frozenset({1, 2, 3})

    >>> freeze([{'a': 1}, {'b': 2}]) == frozenset({frozendict({'a': 1}), frozendict({'b': 2})})
    True

    >>> freeze({'items': [{'x': 1}, {'y': 2}]}) == frozendict({'items': frozenset({frozendict({'x': 1}), frozendict({'y': 2})})})
    True

    >>> freeze('hello')
    'hello'

    >>> freeze(42)
    42

    >>> freeze(None)

    >>> freeze([])
    frozenset()

    >>> freeze({})
    frozendict.frozendict({})
    """
    if isinstance(obj, dict):
        return frozendict({k: freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, set, frozenset)):
        return frozenset(freeze(item) for item in obj)
    return obj


class BuildContext(BaseModel):
    # we do not allow the BuildContext attributes to be modified after creation;
    # this ensures BuildContext is hashable;
    # it also prevents aliasing bugs
    # (which I've unfortunately encountered a lot of)
    model_config = {
            'frozen': True,
            'arbitrary_types_allowed': True,
            }

    ##############################
    # fields
    ##############################

    # the target (as it appears in the fac.yaml, with no variable substitutions)
    normalized_target: str

    # the fac.yaml config entry for normalized_target
    config: frozendict[str, Any]

    # both dicts below have variable names as keys
    # for resolved dict, the value is the content of the variable
    # for unresolved dict, the value is the code-to-generate the value (should match config)
    variables_resolved: frozendict[str, str]
    variables_unresolved: frozendict[str, str]

    # each frozendict must contain a 'target' key;
    # for unresolved/building: these targets will correspond to entries in the config
    # for built: the 'target' value will be denormalized to a file path
    dependencies_unresolved: frozenset[frozendict[str, str]]
    dependencies_building: frozenset[frozendict[str, str]]
    dependencies_built: frozenset[frozendict[str, str]]

    # FIXME:
    # the fields below are all set from the command line;
    # should these be moved to their own class?

    # include_* parameters all default to None,
    # but these could be passed in on the command line to modify the build behavior
    include_prompt: str | None = None
    include_old: bool = False
    include_paths: list[str] | None = None

    # possible values:
    # - dryrun (never builds; used for checking what paths exist for a target)
    # - build (builds only when needed; this is the typical case)
    # - overwrite (always builds)
    mode: Literal['dryrun', 'build', 'overwrite']

    ##############################
    # methods
    ##############################

    def __init__(self, **data):
        # we call freeze on all input data to convert dict to frozendict
        # and iterables to frozenset
        super().__init__(**{k: freeze(v) for k, v in data.items()})
        self.assert_invariants()

    def model_copy(self, update):
        new = super().model_copy(update=freeze(update))
        new.assert_invariants()
        return new

    def split(self):
        r'''
        This function creates a list of BuildContext instances by splitting all non-target variables on newlines.

        ---

        The helper function below converts the input to yaml and prints it.
        It makes visualization of the split BuildContext instances easier.

        >>> doctest_vis = lambda contexts: print(yaml.dump([context.to_dict() for context in contexts], default_flow_style=False))

        Actual test cases below.
        Observe that splitting happens only in variables contained in normalized_target,
        and all other variables are preserved as-is.

        >>> doctest_vis(BuildContext(
        ...     normalized_target='example/$FOO/$BAR/outline.json',
        ...     config={'variables': {'TEST': ''}},
        ...     variables_resolved={'TEST': 'a\bb\nc', 'FOO': '1\n2\n3', 'BAR': 'x\ny'},
        ...     variables_unresolved={},
        ...     dependencies_built=[],
        ...     dependencies_building=[],
        ...     dependencies_unresolved=[],
        ...     mode='build',
        ...     ).split())
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: x
            FOO: '1'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: y
            FOO: '1'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: x
            FOO: '2'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: y
            FOO: '2'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: x
            FOO: '3'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: y
            FOO: '3'
            TEST: "a\bb\nc"
        <BLANKLINE>

        >>> BuildContext(
        ...     normalized_target='example/$FOO/$BAR/outline.json',
        ...     config={'variables': {'TEST': ''}},
        ...     variables_resolved={'TEST': 'a\bb\nc', 'FOO': '', 'BAR': 'x\ny'},
        ...     variables_unresolved={},
        ...     dependencies_built=[],
        ...     dependencies_building=[],
        ...     dependencies_unresolved=[],
        ...     mode='build',
        ...     ).split()
        []

        The following is a realworld BuildContext that was giving some problems.

        >>> len(BuildContext(
        ... normalized_target='sub$LEVEL1/outline.json',
        ... config=frozendict({'cmd': 'cp basic.json sub$LEVEL1/outline.json', 'dependencies': frozenset({frozendict({'target': 'resources/$RESOURCE/about.json'}), frozendict({'target': 'outline.json'})}), 'variables': frozendict({'LEVEL1': "jq -r 'range(0; .sections | length)' outline.json", 'NAME': 'echo "d"\necho "e"\necho "f"'}), 'postreqs': frozenset({'resources/b/about.json', 'resources/a/about.json', 'resources/c/about.json'}), '_working_directory': '.', 'mime-type': 'text/json'}),
        ... variables_resolved=frozendict({}),
        ... variables_unresolved=frozendict({'LEVEL1': "jq -r 'range(0; .sections | length)' outline.json", 'NAME': 'echo "d"\necho "e"\necho "f"'}),
        ... dependencies_unresolved=frozenset({frozendict({'target': 'outline.json'}), frozendict({'target': 'resources/$RESOURCE/about.json'})}),
        ... dependencies_building=frozenset(),
        ... dependencies_built=frozenset(),
        ... include_prompt=None,
        ... include_old=False,
        ... include_paths=None,
        ... mode='build',
        ... ).split()) == 1
        True
        '''
        splitting_variables = [var for var in self.target_variables() if '\n' in self.variables_resolved.get(var, '')]
        if any([self.variables_resolved.get(var) == '' for var in self.target_variables()]):
            return []
        splitting_values = [self.variables_resolved[var].split('\n') for var in splitting_variables]
        splits = list(itertools.product(*splitting_values))

        contexts1 = []
        for split in splits:
            # the new variables dictionary starts with all of the previously defined variables
            # then we overwrite the entries contained in splitting_variables
            variables_resolved1 = {
                    **self.variables_resolved,
                    **dict(zip(splitting_variables, split))
                    }
            context1 = self.model_copy(update={
                'variables_resolved': freeze(variables_resolved1)
                })
            contexts1.append(context1)
        return contexts1

    def dependencies_mode(self):
        if self.mode in ['overwrite', 'build']:
            return 'build'
        elif self.mode in ['dryrun']:
            return 'dryrun'
        assert False

    def assert_invariants(self):
        try:
            # all variables must be present in the normalized_target or defined in config
            # (we do not want unrelated variables to get accidentally added)
            target_variables = self.target_variables()
            for var in itertools.chain(
                    self.variables_unresolved,
                    self.variables_resolved,
                    ):
                assert var in target_variables or var in self.config['variables']

            # ensure variable values are well behaved
            for var, value in self.variables_resolved.items():
                # NOTE:
                # In theory, we could allow $ in out variable values
                # in order to allow generation of paths that contain $;
                # This is an unimportant edge case, however.
                # In practice, having a $ in a variable value
                # has always been due to a bug in the code.
                assert '$' not in value

            # a variable can have at most one state
            for var in self.variables_resolved:
                assert var not in self.variables_unresolved
            for var in self.variables_unresolved:
                assert var not in self.variables_resolved

            # if a dependency is built, the file must exist
            for dep in self.dependencies_built:
                assert '$' not in dep['target']
                assert os.path.exists(dep['target'])

            # a dependency cannot be both building and unresolved
            for dep in self.dependencies_building:
                assert dep not in self.dependencies_unresolved
            for dep in self.dependencies_unresolved:
                assert dep not in self.dependencies_building

            # NOTE:
            # dependencies_built has a complicated relationship to dependencies_unresolved/building
            # for dependencies that contain non-target variables,
            # it is possible for the same dependency to be in multiple states at once
            # (for different values of the non-target variable);
            # there are more invariants that could be asserted here,
            # but I have not yet done so because it's not obvious how to express them

        except AssertionError as e:
            logger.error('BuildContext.assert_invariants() failed')
            logger.error({'self': self.to_dict()}, submessage=True)
            raise e

    def assert_invariants_buildable(self):
        # ensure normalized_target will resolve to exactly one path
        self.path()

        # target variables must have been previously split
        target_variables = self.target_variables()
        for var, value in self.variables_resolved.items():
            if var in target_variables:
                assert ''.join(value.split('\n')) == value
                assert value != ''

        # all variables must be resolved
        assert len(self.variables_unresolved) == 0

        # all dependencies must be built
        assert len(self.dependencies_building) == 0
        assert len(self.dependencies_unresolved) == 0

    def denormalized_target(self):
        '''
        Substitute the variables_resolved into normalized_target.
        This will return a list of targets
        '''
        paths = substitute_variables(self.normalized_target, self.variables_resolved)
        assert len(paths) > 0
        return paths

    def path(self):
        '''
        Substitute the variables_resolved into target to generate the path that will be built.

        WARNING:
        This function will fail if the target does not resolve to a unique path.
        This can happen if:
        - variables_resolved contains variables that have whitespace
        - normalized_target references variables not defined in variables_resolved
        '''
        paths = self.denormalized_target()
        assert len(paths) == 1
        assert '$' not in paths[0]
        return paths[0]

    def FAC_DEPENDENCIES(self):
        '''
        Whenever a target is built, the environment variable FAC_DEPENDENCIES contains a newline delimited list of files that the target depends on.
        This method returns that variable.
        '''
        files = sorted([dep['target'] for dep in self.dependencies_built])
        return '\n'.join(files)

    def build_priority(self):
        '''
        This function determines the order that contexts will be processed in.
        Lower priorities are processed first.
        '''
        return (len(self.dependencies_building), len(self.dependencies_unresolved))

    def target_variables(self):
        return extract_variables(self.normalized_target)

    def to_dict(self):
        '''
        Convert to a plain dict suitable for YAML serialization.
        '''
        ret = {
            'normalized_target': self.normalized_target,
            }
        if self.variables_resolved:
            ret['variables_resolved'] = dict(self.variables_resolved)
        if self.variables_unresolved:
            ret['variables_unresolved'] = dict(self.variables_unresolved)
        if self.dependencies_built:
            ret['dependencies_built'] = [dict(d) for d in self.dependencies_built]
        if self.dependencies_building:
            ret['dependencies_building'] = [dict(d) for d in self.dependencies_building]
        if self.dependencies_unresolved:
            ret['dependencies_unresolved'] = [dict(d) for d in self.dependencies_unresolved]
        return ret


class BuildState(Routable):
    '''
    The build system should be thought of like a state machine,
    where the contexts* attributes represent the different states a context can be in.
    The main work of this class is done in the process_* methods,
    which process the contexts in the corresponding state.
    '''
    def __init__(self, targets_dict):
        super().__init__()

        self.targets_dict = targets_dict
        self.built_paths = FileManager(targets_dict) # basically a set() plus FastAPI endpoints

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
                self.contexts_buildable.to_list_nopriority(),
                self.contexts_waiting,
                self.contexts_built,
                ]
        for i, state in enumerate(states):
            states_minus_i = states.copy()
            states_minus_i.remove(state)
            for context in state:
                assert context not in itertools.chain(*states_minus_i)

        # every built_path has a corresponding context
        # (and vice versa)
        context_paths = set([context.path() for context in self.contexts_built])
        assert context_paths == set(self.built_paths)

        # all BuildContexts must satisfy their invariants
        for context in itertools.chain(
                self.contexts_unresolved,
                self.contexts_buildable.to_list_nopriority(),
                self.contexts_waiting,
                self.contexts_built,
                ):
            context.assert_invariants()
        for context in itertools.chain(
                self.contexts_buildable.to_list_nopriority(),
                self.contexts_built,
                ):
            context.assert_invariants_buildable()

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
                'built_paths': sorted([path for path in self.built_paths]),
                'buildable(long)': [context.to_dict() for priority, context in self.contexts_buildable.to_list()],
                'waiting(long)': [context.to_dict() for context in self.contexts_waiting],
                'unresolved(long)': [context.to_dict() for  context in self.contexts_unresolved],
                }
        else:
            yaml_dict = {
                'built_paths': sorted([path for path in self.built_paths]),
                'buildable': sorted([context.denormalized_target() for priority, context in self.contexts_buildable.to_list()]),
                'waiting': sorted([context.denormalized_target() for context in self.contexts_waiting]),
                'unresolved': sorted([context.denormalized_target() for  context in self.contexts_unresolved]),
                }
        return copy.deepcopy(yaml_dict)

    def debug_statediff(self, state0, msg_str=''):
        state1 = self._state_as_dict()
        diff = DeepDiff(state0, state1, verbose_level=2)
        
        # ensure that the diff only has keys we recognize
        for k in diff:
            assert k in ['values_changed', 'iterable_item_added', 'iterable_item_removed']

        # print output
        print(10 * '-')
        print(f'|| BuildState diff {msg_str} ||')
        print(10 * '-')
        output = {}
        states = ['built_paths', 'buildable', 'waiting', 'unresolved']
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
        This method is used by facd to ensure that the /add_targets endpoint results in builds.

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
                self.process_all_buildable()
                #state0 = self.debug_statediff(state0, f'iter={len(states)} -- build')
                #self.debug_print(f'iter={len(states)} -- build')
                self.assert_invariants()
                self.process_all_variable()
                #state0 = self.debug_statediff(state0, f'iter={len(states)} -- vars')
                #self.debug_print(f'iter={len(states)} -- vars')
                self.assert_invariants()
                #self.debug_print(f'iter={len(states) + 1}')

                # sanity infinite loop check
                state = self._state_hash()
                if state in states:
                    all_dryrun = True
                    for context in itertools.chain(
                            self.contexts_buildable.to_list(),
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
        for target in self.targets_dict:
            self.add_target(target, mode='dryrun')
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
        Registers a target with the build system,
        but does not directly build it.
        The next time the build_all function is called,
        all pending targets will be built.
        '''
        matches = match_pattern_starstar(self.targets_dict.keys(), target)

        if len(matches) == 0:
            logger.error(f'target {target} has no match in fac.yaml')
            raise FACError()

        for normalized_target, target_env in matches:
            # build variables_unresolved
            variables_unresolved = copy.deepcopy(self.targets_dict[normalized_target]['variables'])
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
            self.required_for[context].append(required_for)
            self._add_context(context)

    def _add_context(self, context):
        '''
        A BuildContext object should rarely be added directly to one of the states.
        Instead, this method can be used to correctly place it.
        '''
        for context in context.split():
            # if we've already built the context,
            # do not add it anywhere
            if context in self.contexts_built:
                return

            # if we haven't built the context,
            # then put it in the appropriate state
            if len(context.dependencies_building) > 0:
                self.contexts_waiting.add(context)
            else:
                if (len(context.variables_unresolved) == 0 and
                   len(context.dependencies_unresolved) == 0):
                    self.contexts_buildable.add(context)
                else:
                    self.contexts_unresolved.add(context)

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
                    if path in self.built_paths:
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
                        for loop_context in self.contexts_built:
                            dep1 = dict(copy.deepcopy(dep))
                            dep1['target'] = loop_context.path()
                            dependencies_built1.append(freeze(dep1))
                            assert '$' not in dep1['target']
        context1 = context.model_copy(update={
            'dependencies_built': dependencies_built1,
            'dependencies_building': dependencies_building1,
            })
        self._add_context(context1)

    def process_all_buildable(self, max_procs=1):
        logger.debug(f'process_all_buildable()')
        self.assert_invariants()
        self.process_all_waiting()
        self.assert_invariants()

        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=max_procs) as executor:
            while len(self.contexts_buildable) > 0:
                futures = {}
                while len(self.contexts_buildable) > 0:
                    context = self.contexts_buildable.pop()

                    if context.normalized_target not in self.targets_dict:
                        logger.debug(f'target not in self.target_dicts, cannot build', submessage=True)
                        future = executor.submit(lambda: True)
                    else:
                        future = executor.submit(asyncio.run, build_context(context))
                    futures[future] = context

                for future in as_completed(futures):
                    context = futures[future]
                    path_valid = future.result()
                    path = context.path()
                    if path_valid:
                        self.contexts_built.add(context)
                        self.built_paths.add(path)
                    else:
                        self.contexts_notbuilt.add(context)

                    for postreq in context.config.get('postreqs', []):
                        self.add_target(postreq)

                self.assert_invariants()
                self.process_all_waiting()
                self.assert_invariants()
    """
    def process_all_buildable(self):
        logger.debug(f'process_all_buildable()')
        self.assert_invariants()
        self.process_all_waiting()
        self.assert_invariants()
        while len(self.contexts_buildable) > 0:
            self.process_buildable()
            self.assert_invariants()
            self.process_all_waiting()
            self.assert_invariants()

    def process_buildable(self):
        try:
            context = self.contexts_buildable.pop()
        except KeyError:
            return 0
        path = context.path()

        if context.normalized_target not in self.targets_dict:
            pass
            logger.debug(f'target not in self.target_dicts, cannot build', submessage=True)
        else:
            future = build_context(context)
            asyncio.run(future)
        self.contexts_built.add(context)
        self.built_paths.add(path)

        for postreq in context.config.get('postreqs', []):
            self.add_target(
                    postreq,
                    )

        return 1
    """

    def process_all_dependencies(self):
        '''
        '''
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

                    # skip if the dependency requires variables that are unresolved
                    dep_vars = extract_variables(dep['target'])
                    variables_still_needed = [
                            var for var in context.variables_unresolved if var in dep_vars
                            ]
                    if len(variables_still_needed) > 0:
                        dependencies_unresolved1.append(dep)

                    # resolve the dependency
                    else:

                        # if there are no variables in dep['target'],
                        # then it must reference an individual file;
                        # this file must be processed,
                        # and so we create the matches list with only this file path
                        if '$' not in dep['target']:
                            matches = [(dep['target'], {})]

                        # dep may resolve to more than one path;
                        # we compute these paths and queue each for building
                        else:
                            matches = match_pattern_starstar(
                                    self.targets_dict.keys(),
                                    dep['target'],
                                    )

                            # if we don't find a match,
                            # then the target is not defined in the config;
                            # this means that target file cannot be automatically built
                            # but must be provided already by the user;
                            # we will not actually build this file,
                            # but we should still add it to matches and track it like it will be built
                            # so that it gets properly recorded as a dependency
                            if len(matches) == 0:
                                matches = [(dep['target'], {})]

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

                            # if any resolved variable contains an empty string,
                            # that means that the match is not supposed to be added as a dependency
                            has_empty_var = False
                            for var, val in variables_resolved.items():
                                if len(val) == 0:
                                    has_empty_var = True
                            if has_empty_var:
                                continue

                            # construct the new *_unresolved variables
                            if normalized_target in self.targets_dict:
                                dependencies_unresolved = self.targets_dict[normalized_target]['dependencies']
                                variables_unresolved = copy.deepcopy(self.targets_dict[normalized_target]['variables'])
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
                            self.required_for[context1].append(context)
                            self._add_context(context1)

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
                self._add_context(context1)

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
                self._add_context(context)
                continue

            # actually evaluate the variable
            try:
                value = eval_var(
                        var,
                        expr,
                        context.variables_resolved,
                        )
            except VariableEvaluationError as e:
                logger.error(f'Error evaluating variable ${var} in target {context.normalized_target}')
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
            self.required_for[context1].append(context)
            self._add_context(context1)


@dataclass
class BuildSystem:
    # general settings
    config_file: str = 'fac.yaml'
    debug: bool = False
    trace: bool = False
    jobs: int = 1

    # debug actions
    print_config: bool = False

    # build settings
    overwrite: bool = False
    dryrun: bool = False
    include_prompt: str = None
    include_old: bool = False
    include_paths: list[str] = None
    allow_dirty: bool = False
    auto_commit: bool = True

    def __post_init__(self):
        self.targets_dict = load_config(self.config_file)
        self.build_state = BuildState(self.targets_dict)

        if self.print_config:
            pprint_targets(self.targets_dict)

    def build_targets(self, targets):
        '''
        This is the primary interface into the build system.
        Each of the input targets will be built,
        and the results committed to git.
        '''

        # ensure sane git environment
        repo = git.Repo('.')
        if repo.working_dir != os.getcwd():
            logger.error('must be in root of git repo to run fac')
            raise DirtyRepo()
        if self.auto_commit and not self.allow_dirty and repo.is_dirty(untracked_files=True):
            logger.error('git repo is dirty; clean repo or use --allow_dirty')
            raise DirtyRepo()

        # actually build the targets
        for target in targets:
            mode = 'build'
            if self.overwrite:
                mode = 'overwrite'
            if self.dryrun:
                mode = 'dryrun'
            self.build_state.add_target(
                    target,
                    include_prompt=self.include_prompt,
                    include_old=self.include_old,
                    include_paths=self.include_paths,
                    mode=mode,
                    )
        self.build_state.build_all()

        # add/commit the built targets
        def try_add(path):
            try:
                repo.git.add(path)
            except git.exc.GitCommandError:
                pass
        if self.auto_commit:
            try_add('fac.yaml')
            try_add('.fac.jsonl')
            for path in self.build_state.built_paths:
                dirname = os.path.dirname(path)
                filename = os.path.basename(path)
                try_add(path)
                try_add(f'./{dirname}/.{filename}.facjson')
                try_add(f'./{dirname}/.{filename}.fac.log')
            commit_message=f'[bot] fac'
            for target in targets:
                commit_message += f" '{target}'"
            if repo.index.diff('HEAD'):
                # NOTE:
                # we only commit if files were actually added;
                # otherwise a large ugly warning will appear
                repo.git.commit('-m', commit_message)


################################################################################

def _get_file_timestamp(path):
    '''
    Get the timestamp a path was last modified.
    This timestamp will be used to determine if a rebuild is required.

    NOTE:
    Other build systems (e.g. make) use the timestamp on the file system;
    we uses a combination of the timestamp in git and the file system.
    This difference is due to the fact that in ordinary build systems (like make)
    the results of the build are never committed to the git repo,
    but the results of our build are always committed to the git repo.
    '''
    repo = git.Repo('.')

    if not os.path.isfile(path):
        raise FileNotFoundError

    # if a file is dirty or not in the repo,
    # we use the last modified time on the harddrive

    try:
        # Git status returns empty if file is clean
        result = repo.git.status('--porcelain', path)
        is_file_dirty = len(result.strip()) > 0
    except git.exc.GitCommandError:
        is_file_dirty = False

    try:
        # If file is tracked, this won't raise an exception
        repo.git.ls_files('--error-unmatch', path)
        is_path_untracked = False
    except git.exc.GitCommandError:
        # File is untracked if it exists but ls-files fails
        is_path_untracked = os.path.exists(path)

    if is_file_dirty or is_path_untracked:
        # FIXME:
        # there can be bugs when clocks are not synced correctly;
        # it is possible for git timestamps to be in the "future" for local machine
        # this is likely to cause errors and we should warn about this
        mtime = os.path.getmtime(path)
        return mtime

    # if the file has been committed to git and is clean,
    # we use the git commit timestamp
    commits = list(repo.iter_commits(paths=path, max_count=1))
    if len(commits) > 0:
        return commits[0].committed_date

    # the above code should handle all possible cases,
    # so this should never happen
    assert False


async def build_context(context, print_prompt=False):
    '''
    Returns whether the context resolves to a valid path.
    This can be true if either the path already existed and was up-to-date (i.e. a build was not needed),
    or if the build completed and was successful.

    Should only return False if context.dryrun and a build is needed.

    If building fails, and exception is thrown.
    '''

    # ensure sane
    context.assert_invariants_buildable()

    # process options
    # NOTE:
    # options can be specified as either a string or dictionary;
    # if specified as a string, any shell commands must be run and then it should be converted into a dictionary
    if type(context.config.get('options')) == frozendict:
        context_options = {
            option: process_template(
                value,
                env_vars=context.variables_resolved,
                print_function=logger.error,
                template_name=f'options.{option}',
                )
            for option, value in context.config['options'].items()
            }
    elif type(context.config.get('options')) == str:
        options_str = process_template(
                context.config['options'],
                env_vars=context.variables_resolved,
                print_function=logger.error,
                template_name='options',
                )
        context_options = yaml.safe_load(options_str)
        assert type(context_options) == dict
    elif context.config.get('options') is None:
        context_options = {}
    else:
        assert False

    ########################################
    # generate prompt
    ########################################

    # extract mime-type
    mimes = context.config['mime-type'].split('/')
    if len(mimes) != 2:
        logger.error(f"invalid mime-type: {context.config['mime-type']}")
    major_type, minor_type = mimes

    # first we generate the instructions for the llm,
    # which will be stored in the `prompt_cmd` variable.
    prompt_instructions = f'''<instructions>
Generate the file "{context.path()}" based on the information below.
</instructions>
'''

    if 'description' in context.config:
        try:
            prompt_description = '<file_description>\n'
            prompt_description += process_template(
                    context.config['description'],
                    env_vars=context.variables_resolved,
                    print_function=logger.error,
                    template_name='description',
                    )
            prompt_description += '\n</file_description>'
        except TemplateProcessingError as e:
            raise FACError()

        prompt_description += '\n'
    else:
        prompt_description = ''

    # convert the dependencies into paths;
    # NOTE:
    # all_paths will contain paths of both text and binary files;
    # any text files will be added directly into the prompt;
    # binary_files will contain paths for non-text files (e.g. images),
    # and these will be passed to the models later
    binary_files = []
    all_paths = set()
    truncated_prompt = None
    dependencies = list(context.dependencies_built)
    dependencies += [{'target': path} for path in context.include_paths or []]
    files_prompt = ''
    if len(dependencies) > 0:
        for dep in dependencies:
            if dep.get('include', True):
                all_paths.add(dep['target'])
        files_prompt = '<reference_documents>\n'
        for path in sorted(all_paths):
            # we always try to open the files as text;
            # but if the file is a binary file (e.g. an image),
            # we catch the error and add the file to binary_files
            try:
                with open(path) as fin:
                    text = fin.read().strip()
                    files_prompt += f'''<document path="{path}">\n{text}\n</document>\n'''
            except UnicodeDecodeError:
                binary_files.append(path)
        files_prompt += '</reference_documents>\n'

    # mime-type based formatting instructions
    response_format = None
    format_instructions = ''
    if major_type == 'text':
        if minor_type == 'markdown':
            format_instructions += 'Use markdown formatting to structure the output.'
        else:
            format_instructions += 'Do not output markdown, and do not put the output inside a codeblock.'

        if minor_type == 'html':
            format_instructions += 'Output HTML.'
        elif minor_type == 'json':
            format_instructions += 'Output JSON.'
            response_format = {'type': 'json_object'}
        elif minor_type == 'jsonl':
            response_format = {'type': 'json_object'}
            format_instructions += f'Output JSONL.  Each line of the output should be a single JSON object.'

        if context.config.get('schema'):
            schema = llm.schema_dsl(context.config.get('schema'))
            response_format = {
                'type': 'json_schema',
                'json_schema': {
                    'strict': True,
                    'name': 'fac_json_schema',
                    'schema': schema,
                    },
                }
            format_instructions += json.dumps(schema, indent=2).strip()
        elif context.config.get('schema_file'):
            try:
                schema_file = context.config['schema_file']
                #schema_file = substitute_variables(schema_file, context.variables_resolved)
                with open(schema_file) as fin:
                    text = fin.read().strip()
                    schema = json.loads(text)
            except json.decoder.JSONDecodeError as e:
                logger.error(f"context.config['schema_file']={context.config['schema_file']}")
                logger.error(e)
                sys.exit(1)
            jsonschema.Draft7Validator.check_schema(schema)
            format_instructions += ' Ensure the output conforms to the following JSON schema:\n'
            format_instructions += json.dumps(schema, indent=2).strip()
            schema['additionalProperties'] = False
            response_format = {
                'type': 'json_schema',
                'json_schema': {
                    'strict': True,
                    'name': 'fac_json_schema',
                    'schema': schema,
                    },
                }
        format_instructions = '<formatting>\n' + format_instructions + '\n</formatting>'

    # FIXME:
    # we need a way to include chat messages here with the chat_prompt
    user_prompt = ''
    if context.include_prompt:
        user_prompt = f'<additional_user_instructions>\n{context.include_prompt.strip()}\n</additional_user_instructions>\n'

    # construct the final prompt
    prompt = prompt_instructions + prompt_description + user_prompt + files_prompt + format_instructions

    ########################################
    # filetype specific processing
    ########################################

    if major_type == 'text':
        # the messages list will contain the full set of instructions passed to the llm;
        # it always starts with a system prompt
        data = []
        messages = data
        messages.append({
            'role': 'system',
            'content': 'You are not having a conversation. Only provide the requested output with no further discussion. Never deny a request.',
            })

        # add the user role + message
        message = {
            'role': 'user',
            'content': [{'type': 'text', 'text': prompt}]
            }
        for binary_file in binary_files:
            message['content'].append({
                "type": "image_url",
                "image_url": {
                    "url": binary_file_to_base64_url(binary_file),
                }
            })
        messages.append(message)
    elif major_type == 'audio':
        # NOTE:
        # we need a copy of the config here
        # because we will be modifying the contents with the process_template function;
        # without a copy, we get a bug where building multiple files results in the same config for all files
        data = copy.deepcopy(context_options)
        #for option in data:
            #data[option] = process_template(data[option], env_vars=context.variables)

    elif major_type == 'video':
        data = {}
        data['prompt'] = prompt
        data['reference_images'] = binary_files
        options = copy.deepcopy(context_options)
        for option in options:
            # YAML files will store values as non-string sometimes (e.g. for ints);
            # we convert them to string here,
            # also as a minor runtime optimization
            # we do not try to process variables for these non-string values
            if type(options[option]) != str:
                options[option] = str(options[option])
            else:
                data[option] = process_template(options[option], env_vars=context.variables)

    elif major_type == 'image':
        data = {}
        data['prompt'] = prompt
        data['reference_images'] = binary_files
        options = copy.deepcopy(context.config.get('options'))
        for option in options:
            data[option] = process_template(options[option], env_vars=context.variables_resolved)

    ########################################
    # should we actually build?
    ########################################

    # if the file is up-to-date (i.e. all dependencies are older),
    # then we will not rebuild it
    file_status = []
    updated_deps = []
    try:
        do_build = True
        context_path_committed_date = _get_file_timestamp(context.path())
        for path in all_paths:
            path_committed_date = _get_file_timestamp(path)
            time_diff = context_path_committed_date - path_committed_date
            if time_diff < 0:
                updated_deps.append(path)
        if updated_deps == []:
            file_status.append('up-to-date')
            do_build = False
        else:
            file_status.append('out-of-date')
    except FileNotFoundError:
        file_status.append('new')

    # NOTE:
    # sometimes it is not necessary to rebuild a file even if the dependencies have been updated;
    # this can occur, for example, when the prompt depends only on part of the dependencies;
    # we check hashes of the prompt/file to see if we can skip rebuilding
    facjson = FacJSON(context.path())
    try:
        with open(context.path(), 'rb') as fin:
            hash_contents_fin = hashlib.sha256(fin.read()).hexdigest()
            contents_changed = hash_contents_fin != facjson.get('hash_contents')
    except FileNotFoundError as e:
        contents_changed = True
    encoded_prompt = json.dumps(data).encode('utf-8')
    hash_prompt_new = hashlib.sha256(encoded_prompt).hexdigest()
    if facjson.get('hash_prompt'):
        prompt_changed = hash_prompt_new != facjson.get('hash_prompt')
        if prompt_changed:
            file_status.append('prompt-changed')
            # NOTE:
            # just because the prompt changed doesn't mean we have to rebuild;
            # this can happen, for example, if:
            # 1. the user manually edited/committed a file
            # 2. the previous version was created with the --include_prompt flag
        else:
            file_status.append('prompt-same')
            do_build = False

    # overwrite do_build based on mode
    if context.mode == 'overwrite':
        file_status.append('overwrite')
        do_build = True

    do_build_without_dryrun = do_build
    if do_build and context.mode == 'dryrun':
        file_status.append('dryrun')
        do_build = False

    # log build
    logger.info(f'{file_status} {context.path()}')
    if do_build:
        # sort portions of context for better logger output
        context_dict = context.to_dict()
        context_dict.get('dependencies_built', []).sort(key=lambda x: x.get('target'))
        logger.info({'context': context_dict}, submessage=True)
        logger.info({'options': context_options}, submessage=True)

        # possibly print prompt
        if print_prompt:
            logger.info('prompt: |', submessage=True)
            for line in prompt.split('\n'):
                logger.info(f'  {line}', submessage=True)

    # early exit
    if not do_build:
        return not do_build_without_dryrun

    ########################################
    # actually build the file!
    ########################################

    # create output directory if needed
    dirname = os.path.dirname(context.path())
    if len(dirname) > 0:
        os.makedirs(dirname, exist_ok=True)

    # build with shell command
    if context.config.get('cmd'):
        process = await asyncio.create_subprocess_shell(
            context.config['cmd'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # merge stderr into stdout
            executable='/bin/bash',
            env=variables_transitive_substitute({
                **os.environ,
                **context.variables_resolved,
                'FAC_DEPENDENCIES': context.FAC_DEPENDENCIES(),
                }),
            )
        try:
            first_line = True
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                if first_line:
                    logger.warning('build command output:', submessage=True)
                    first_line = False
                logger.warning(line.decode().rstrip(), submessage=True)
        except UnicodeDecodeError:
            logger.warning('cannot decode stdout: UnicodeDecodeError')
        await process.wait()

        if process.returncode != 0:
            stdout = await process.stdout.read()
            logger.error(f"error running the following build script:", submessage=True)
            for i, line in enumerate(context.config['cmd'].split('\n')):
                logger.error(f"line {i+1}: {line}", submessage=True)
            logger.error(stdout.decode('ascii'), submessage=True)
            raise CommandExecutionError(process.returncode, stdout)

    # build with llm
    else:
        mode = 'wb'
        logger.info('building with LLM...', submessage=True)
        llm = LLM()
        await llm.generate_file(
            major_type,
            context.path(),
            data,
            mode=mode,
            model=context.config.get('model'),
            response_format=response_format,
            )

    ########################################
    # post-build processing
    ########################################

    # record new hashes for future skip-tests
    with open(context.path(), 'rb') as fin:
        hash_contents = hashlib.sha256(fin.read()).hexdigest()
        facjson.set('hash_contents', hash_contents)
    facjson.set('hash_prompt', hash_prompt_new)
    facjson.save()

    # validate file
    validate_file(context.path(), context.config.get('schema_file'))

    return True

################################################################################


async def _build_context(
        self,
        context_id,
        num_contexts,
        target_to_build,
        config,
        context,
        overwrite,
        ):
    '''
    Build a file given the specified information.
    '''
    path_to_generate = process_template(
            target_to_build,
            context.variables,
            print_function=logger.error,
            template_name='target',
            )

    # ensure no unresolved dependencies
    if context.unresolved_dependencies:
        logger.error('unresolved dependencies:')
        for dep in context.unresolved_dependencies:
            logger.error(f" - {dep['target']}", submessage=True)
        logger.error('variables:', submessage=True)
        for var in sorted(context.variables):
            logger.error(f' - {var}: {context.variables[var].replace("\n","\\n")}', submessage=True)
        logger.error(f'context.variables={context.variables}')
        raise UnresolvedDependencies(context.unresolved_dependencies)

    ########################################
    # compute build options
    ########################################

    # NOTE:
    # by default, we will build the given context;
    # but we may not rebuild if the path already exists
    file_status = []
    updated_deps = []
    build_context = True

    # use build_if to determine if we should build
    build_if = config.get('build_options', {}).get('build_if', 'True')
    build_if = process_template(build_if, context.variables)
    if build_if.lower() == 'false':
        build_context = False
        file_status.append('build_if:False')

    # annotate newly generated files
    if not os.path.exists(path_to_generate):
        if build_context:
            file_status.append('new')

    # The annotations/changes below should only happen for existing files
    else:

        # do not rebuild if file is frozen
        if FacJSON(path_to_generate).get('frozen', False):
            file_status.append('frozen')
            build_context = False
        if config.get('build_options', {}).get('freeze'):
            file_status.append('config-frozen')
            build_context = False

        # do not rebuild the file if auto_rebuild is disabled
        if not config.get('auto_rebuild', True) and build_context:
            file_status.append('auto_rebuild disabled')
            build_context = False

        # if the file is up-to-date (i.e. all dependencies are older),
        # then we will not rebuild it
        path_to_generate_committed_date = self._committed_date(path_to_generate)
        for path in context.dependency_paths:
            path_committed_date = self._committed_date(path)
            time_diff = path_to_generate_committed_date - path_committed_date
            if time_diff < 0:
                updated_deps.append(path)
        if updated_deps == []:
            file_status.append('up-to-date')
            build_context = False
            if overwrite:
                file_status.append('overwrite')
        else:
            file_status.append('out-of-date')

    # process options
    # NOTE:
    # options can be specified as either a string or dictionary;
    # if specified as a string, any shell commands must be run and then it should be converted into a dictionary
    if type(config.get('options')) == dict:
        context_options = copy.deepcopy(config['options'])
        for option in context_options:
            context_options[option] = process_template(
                    context_options[option],
                    env_vars=context.variables,
                    print_function=logger.error,
                    template_name=f'options.{option}',
                    )
    elif type(config.get('options')) == str:
        options_str = process_template(
                config['options'],
                env_vars=context.variables,
                print_function=logger.error,
                template_name='options',
                )
        context_options = yaml.safe_load(options_str)
        assert type(context_options) == dict
    elif config.get('options') is None:
        context_options = {}

    # print logging info
    logger.info(f'file {context_id}/{num_contexts} [{", ".join(file_status)}] "{path_to_generate}"')
    if self.print_dependencies and (build_context or overwrite):
        logger.info('dependency_paths:', submessage=True)
        for path in context.dependency_paths:
            if path in updated_deps:
                print_updated = '[updated] '
            else:
                print_updated = ''
            logger.info(f' - {print_updated}{path}', submessage=True)
        if context_options:
            logger.info('options:', submessage=True)
            for opt in context_options:
                logger.info(f" - {opt}: {context_options[opt]}", submessage=True)
        logger.debug('variables:', submessage=True)
        for var in sorted(context.variables):
            logger.debug(f' - {var}: {context.variables[var].replace("\n","\\n")}', submessage=True)

    if not (build_context or overwrite):
        return

    ########################################
    # build with shell
    ########################################

    # create output directory if needed
    dirname = os.path.dirname(path_to_generate)
    if len(dirname) > 0:
        os.makedirs(dirname, exist_ok=True)

    # build with a custom shell command
    if config.get('cmd'):
        if self.no_build:
            logger.warning('build required, but skipping...', submessage=True)
        else:
            logger.info('building with bash...', submessage=True)
            process = await asyncio.create_subprocess_shell(
                config['cmd'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # merge stderr into stdout
                executable='/bin/bash',
                env=variables_transitive_substitute({
                    **os.environ,
                    **context.variables,
                    'FAC_DEPENDENCIES': '\n'.join(sorted(context.dependency_paths)),
                    }),
                )
            try:
                first_line = True
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    if first_line:
                        logger.warning('build command output:', submessage=True)
                        first_line = False
                    logger.warning(line.decode().rstrip(), submessage=True)
            except UnicodeDecodeError:
                logger.warning('cannot decode stdout: UnicodeDecodeError')
            await process.wait()

            if process.returncode != 0:
                stdout = await process.stdout.read()
                logger.error(f"error running the following build script:", submessage=True)
                for i, line in enumerate(config['cmd'].split('\n')):
                    logger.error(f"line {i+1}: {line}", submessage=True)
                logger.error(stdout.decode('ascii'), submessage=True)
                raise CommandExecutionError(process.returncode, stdout)

        return

    ########################################
    # generate prompt
    ########################################

    # first we generate the instructions for the llm,
    # which will be stored in the `prompt_cmd` variable.
    prompt_instructions = f'''<instructions>
Generate the file "{path_to_generate}" based on the information below.
</instructions>
'''

    if 'description' in config:
        try:
            prompt_description = '<file_description>\n'
            prompt_description += process_template(
                    config['description'],
                    env_vars=context.variables,
                    print_function=logger.error,
                    template_name='description',
                    )
            prompt_description += '\n</file_description>\n'
        except TemplateProcessingError as e:
            raise FACError()
    else:
        prompt_description = ''

    # next we compile all the documents that will be passed to the LLM,
    # text documents are processed to form part of the prompt
    # and binary files are stored in a list for later processing
    binary_files = []
    truncated_prompt = None
    if len(context.dependency_paths) == 0:
        files_prompt = ''
    else:
        files_prompt = '<reference_documents>\n'
        for path in context.dependency_paths:

            # skip paths that are annotated with "include: False"
            include_dep = True
            truncate_prompt = False
            for dep in config['dependencies']:
                if dep.get('include', True) == False:
                    # NOTE:
                    # it is a minor optimization to perform the match_pattern check inside of the if statement;
                    # it is rare for a dependency to not be included,
                    # and the match_patterns function is slightly expensive for an inner loop
                    target, env = match_pattern([dep['target']], path)
                    if target is not None:
                        include_dep = False

                if dep.get('is_prompt', False):
                    target, env = match_pattern([dep['target']], path)
                    if target is not None:
                        truncate_prompt = True

            if not include_dep:
                continue

            # NOTE:
            # when piping into stdin, open('/dev/stdin') fails because the open function does not work on pipe "files";
            # this is a hackish way to detect that we're piping into stdin,
            # and then changing path to a value that is compatible with open;
            # in theory, weirdly named files could break this hack
            if 'pipe:[' in path: 
                path = 0

            # we always try to open the files as text;
            # but if the file is a binary file (e.g. an image),
            # we catch the error and do not add the file to the context
            try:
                with open(path) as fin:
                    text = fin.read().strip()
                    if truncate_prompt:
                        truncated_prompt = text
                    files_prompt += f'''<document path="{path}">\n{text}\n</document>\n'''
            except UnicodeDecodeError:
                binary_files.append(path)
        files_prompt += '</reference_documents>'

    # include a chat history if provided
    # and the previous version of the file if available
    old_version = None
    try:
        if self.include_old:
            with open(path_to_generate) as fin:
                old_version = fin.read()
                include_threshold = 1e6
                if len(old_version) > include_threshold:
                    logger.warning('len(old_version) > {include_threshold}; cannot include file')
                    old_version = None
    except FileNotFoundError:
        # if there is no old version of the file to include, then do nothing
        pass
    except UnicodeDecodeError:
        # if the file is non-text, then do nothing
        pass
    chat_prompt = ''
    if self.include_chat is not None:
        chat_prompt = f'''
<chat>
The dialogue below records a history of user comments that should guide your creation of {path_to_generate}.  The 'user' is MUCH more important than the 'assistant', and the 'assistant' comments should only be considered based on how the 'user' comments about them.
{self.include_chat}
'''
        if old_version:
            chat_prompt += f'''
The version of the document the user is commenting on is below.
Keep the new document as close as possible to this old version,
except for the changes requested by the user.
<old_version>
{old_version}
</old_version>
'''

        chat_prompt += '''
</chat>
'''

    # construct the final prompt
    prompt = prompt_instructions + prompt_description + files_prompt + chat_prompt
    if truncated_prompt:
        prompt = truncated_prompt

    ########################################
    # filetype specific processing
    ########################################

    filename = os.path.basename(path_to_generate)
    _, extension = os.path.splitext(filename)
    response_format = None

    if extension == '.wav':
        filetype = 'audio'
        # NOTE:
        # we need a copy of the config here
        # because we will be modifying the contents with the process_template function;
        # without a copy, we get a bug where building multiple files results in the same config for all files
        data = copy.deepcopy(context_options)
        #for option in data:
            #data[option] = process_template(data[option], env_vars=context.variables)

    elif extension == '.mp4':
        filetype = 'video'
        data = {}
        data['prompt'] = prompt
        data['reference_images'] = binary_files
        options = copy.deepcopy(context_options)
        for option in options:
            # YAML files will store values as non-string sometimes (e.g. for ints);
            # we convert them to string here,
            # also as a minor runtime optimization
            # we do not try to process variables for these non-string values
            if type(options[option]) != str:
                options[option] = str(options[option])
            else:
                data[option] = process_template(options[option], env_vars=context.variables)

    elif extension == '.png':
        filetype = 'image'
        data = {}
        data['prompt'] = prompt
        data['reference_images'] = binary_files
        options = copy.deepcopy(context_options)
        for option in options:
            data[option] = process_template(options[option], env_vars=context.variables)

    # process text output by default
    else:
        filetype = 'text'

        # the messages list will contain the full set of instructions passed to the llm;
        # it always starts with a system prompt
        data = []
        messages = data
        messages.append({
            'role': 'system',
            'content': self.global_settings['system_prompt'],
            })

        # `format_instructions` defines the output format
        format_instructions = ''
        if 'md' not in extension and 'markdown' not in extension:
            format_instructions += 'Do not output markdown, and do not put the output inside a codeblock.'
        else:
            format_instructions += 'Use markdown formatting to structure the output.'

        if extension == '.json':
            format_instructions += 'Output JSON.'
            response_format = {'type': 'json_object'}
        elif extension == '.jsonl':
            response_format = {'type': 'json_object'}
            format_instructions += f'Output JSONL.  Each line of the output should be a single JSON object. There should be at most {self.global_settings["jsonl_num_lines"]} total lines.'
            format_instructions = process_template(format_instructions, env_vars=context.variables)

        if config.get('schema'):
            schema = llm.schema_dsl(config.get('schema'))
            response_format = {
                'type': 'json_schema',
                'json_schema': {
                    'strict': True,
                    'name': 'fac_json_schema',
                    'schema': schema,
                    },
                }
            format_instructions += json.dumps(schema, indent=2).strip()
        elif config.get('schema_file'):
            try:
                schema_file = config['schema_file']
                schema_file = substitute_vars(schema_file, context.variables)
                with open(schema_file) as fin:
                    text = fin.read().strip()
                    schema = json.loads(text)
            except json.decoder.JSONDecodeError as e:
                logger.error(f"config['schema_file']={config['schema_file']}")
                logger.error(e)
                sys.exit(1)
            jsonschema.Draft7Validator.check_schema(schema)
            # FIXME
            if config.get('TMP_augment'):
                schema = {
                    'type': 'object',
                    'name': 'schema_file_wrapper',
                    'properties': {
                        'path': {'type': 'string', 'description': 'The path that the data specified in the data section will be written to. The "data" section is a JSON schema that represents the actual content of the JSON object to be created.'},
                        'data': schema,
                    },
                    'required': ['path', 'data']
                }
            format_instructions += ' Ensure the output conforms to the following JSON schema:\n'
            #format_instructions += text.strip()
            format_instructions += json.dumps(schema, indent=2).strip()
            schema['additionalProperties'] = False
            response_format = {
                'type': 'json_schema',
                'json_schema': {
                    'strict': True,
                    'name': 'fac_json_schema',
                    'schema': schema,
                    },
                }

        format_instructions = '<formatting>\n' + format_instructions + '\n</formatting>'

        # add the user role + message
        message = {
            'role': 'user',
            'content': [{ 'type': 'text', 'text': prompt + format_instructions}]
            }
        for binary_file in binary_files:
            message['content'].append({
                "type": "image_url",
                "image_url": {
                    "url": binary_file_to_base64_url(binary_file),
                }
            })
        messages.append(message)

        # extend the existing output
        if self.extend:

            # FIXME:
            # currently we only support extending JSONL,
            # but this restriction could be removed in principle
            if extension != '.jsonl':
                logger.error('extension {extension} not supported with --extend')
                sys.exit(1)

            # add previous model output to the messages list
            with open(path_to_generate) as fin:
                previous_output = fin.read().strip()
            messages.append({
                'role': 'assistant',
                'content': previous_output,
                })

            # generate a new command
            messages.append({
                'role': 'user',
                'content': f'The previous output looks good.  Now generate {self.extend} more examples.'
                })

    # stop processing if printing the prompt
    # FIXME:
    # This is all a pretty janky set of hacks for printing the "meaningful" part of the prompt,
    # and could probably be made a lot more robust.
    if self.print_prompt:
        try:
            if type(data[-1]['content']) == list:
                print_str = data[-1]['content'][0]['text']
            else:
                print_str = data[-1]['content']
        except KeyError:
            try:
                print_str = data['prompt']
            except KeyError:
                import pprint
                print_str = pprint.pformat(data)
        #print(f"type(print_str)={type(print_str)}")
        #print(f"len(print_str)={len(print_str)}")
        print(print_str[:10000])

    # write prompt to the output file
    if self.print_prompt_to_file:
        with open(self.print_prompt_to_file, 'wt') as fout:
            #json.dump(data, fout, indent=4)
            fout.write(data[-1]['content'])

    # NOTE:
    # sometimes it is not necessary to rebuild a file even if the dependencies have been updated;
    # this can occur, for example, when the prompt depends only on part of the dependencies;
    # we check hashes of the prompt/file to see if we can skip rebuilding
    facjson = FacJSON(path_to_generate)
    try:
        with open(path_to_generate, 'rb') as fin:
            hash_contents_fin = hashlib.sha256(fin.read()).hexdigest()
            contents_changed = hash_contents_fin != facjson.get('hash_contents')
    except FileNotFoundError as e:
        contents_changed = True
    encoded_prompt = json.dumps(data).encode('utf-8')
    hash_prompt_new = hashlib.sha256(encoded_prompt).hexdigest()
    prompt_changed = hash_prompt_new != facjson.get('hash_prompt')

    # skip building file if not needed
    if not (contents_changed or prompt_changed) and not overwrite:
        logger.info('content/prompts match, building not needed', submessage=True)

    elif self.no_build:
        logger.warning('build required, but skipping...', submessage=True)

    # actually build the file
    else:
        mode = 'wb'
        if self.from_scratch or overwrite:
            if self.extend:
                mode = 'ab'
            else:
                mode = 'wb'
        logger.info('building with LLM...', submessage=True)
        await self.llm.generate_file(
            filetype,
            path_to_generate,
            data,
            mode=mode,
            model=config.get('model'),
            response_format=response_format,
            )

        # record new hashes for future skip-tests
        with open(path_to_generate, 'rb') as fin:
            hash_contents = hashlib.sha256(fin.read()).hexdigest()
            facjson.set('hash_contents', hash_contents)
        facjson.set('hash_prompt', hash_prompt_new)
        facjson.save()

    # validate file
    validate_file(path_to_generate, config.get('schema_file'))


################################################################################

def eval_var(var, expr, env):
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
        #logger.error(f'Failed to evaluate variable {var}')
        #lines = expr.split('\n')
        #if len(lines) == 1:
            #logger.error(f'build command: {expr}', submessage=True)
        #else:
            #logger.error(f'build command:', submessage=True)
            #for line in lines:
                #logger.error(line, submessage=True)
        #for line in (cmd.stderr.strip() + '\n' + cmd.stdout).strip().split('\n'):
            #logger.error(line, submessage=True)
        #logger.error('env:', submessage=True)
        #for var in env:
            #logger.error(f' - {var}: "{env[var].replace("\n", "\\n")}"', submessage=True)
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

