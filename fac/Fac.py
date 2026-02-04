# stdlib imports
from collections import namedtuple, defaultdict
from dataclasses import dataclass
from typing import NamedTuple
import asyncio
import itertools

# external imports
from frozendict import frozendict
from pydantic import BaseModel
import yaml

# project imports
from fac.Config import *
from fac.Errors import *
from fac.util.PrioritySet import PrioritySet
from fac.util.templates import *
from fac.utils import *

# setup logging
from fac.Logging import *
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)


def freeze(obj):
    """Recursively convert dicts to frozendicts and iterables to frozensets.

    >>> freeze({'a': 1, 'b': 2})
    frozendict({'a': 1, 'b': 2})

    >>> freeze({'nested': {'x': 1}})
    frozendict({'nested': frozendict({'x': 1})})

    >>> freeze([1, 2, 3])
    frozenset({1, 2, 3})

    >>> freeze({1, 2, 3})
    frozenset({1, 2, 3})

    >>> freeze([{'a': 1}, {'b': 2}])
    frozenset({frozendict({'a': 1}), frozendict({'b': 2})})

    >>> freeze({'items': [{'x': 1}, {'y': 2}]})
    frozendict({'items': frozenset({frozendict({'x': 1}), frozendict({'y': 2})})})

    >>> freeze('hello')
    'hello'

    >>> freeze(42)
    42

    >>> freeze(None)

    >>> freeze([])
    frozenset()

    >>> freeze({})
    frozendict({})
    """
    if isinstance(obj, dict):
        return frozendict({k: freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, set, frozenset)):
        return frozenset(freeze(item) for item in obj)
    return obj


class BuildContext(BaseModel):
    # we do not allow the BuildContext attributes to be modified after creation
    # this ensures they are hashable
    model_config = {
            'frozen': True,
            'arbitrary_types_allowed': True,
            }

    # build context is uniquely hashed/deduped based on the following fields
    normalized_target: str
    variables_resolved: frozendict[str, str]
    variables_unresolved: frozendict[str, str]
    dependencies_built: frozenset[frozendict[str, str]]
    dependencies_building: frozenset[frozendict[str, str]]
    dependencies_unresolved: frozenset[frozendict[str, str]]

    def __init__(self, **data):
        # we call freeze on all input data to convert dict to frozendict
        # and iterables to frozenset
        super().__init__(**{k: freeze(v) for k, v in data.items()})

    def assert_invariants(self):
        try:
            # all variables must be present in the normalized_target
            target_variables = self.target_variables()
            for var in itertools.chain(
                    self.variables_unresolved,
                    self.variables_resolved,
                    ): 
                assert var in target_variables

            # a variable can have at most one state
            for var in self.variables_resolved:
                assert var not in self.variables_unresolved
            for var in self.variables_unresolved:
                assert var not in self.variables_resolved

            # a dependency can have at most one state
            for dep in self.dependencies_built:
                assert dep not in self.dependencies_building
                assert dep not in self.dependencies_unresolved
            for dep in self.dependencies_building:
                assert dep not in self.dependencies_built
                assert dep not in self.dependencies_unresolved
            for dep in self.dependencies_unresolved:
                assert dep not in self.dependencies_building
                assert dep not in self.dependencies_built

        except AssertionError as e:
            logger.error('BuildContext.assert_invariants() failed')
            logger.error({'self': self.to_dict()}, submessage=True)
            raise e

    def assert_invariants_buildable(self):
        # ensure normalized_target will resolve to exactly one path
        self.path()

        # all variables must be resolved
        assert len(self.variables_unresolved) == 0

        # all dependencies must be built
        assert len(self.dependencies_building) == 0
        assert len(self.dependencies_unresolved) == 0

    def build_priority(self):
        '''
        This function determines the order that contexts will be processed in.
        Lower priorities are processed first.
        '''
        return (len(self.dependencies_building), len(self.dependencies_unresolved))

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
        assert(len(paths) == 1)
        assert('$' not in paths[0])
        return paths[0]

    def target_variables(self):
        return extract_variables(self.normalized_target)

    def to_dict(self):
        """Convert to a plain dict suitable for YAML serialization."""
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


class BuildState:
    '''
    The build system should be thought of like a state machine,
    where the contexts* attributes represent the different states a context can be in.
    The main work of this class is done in the process_* methods,
    which process the contexts in the corresponding state.
    '''
    def __init__(self, targets_dict):
        self.built_paths = set()
        self.targets_dict = targets_dict

        # the states
        self.contexts_unresolved = set()
        self.contexts_buildable = PrioritySet(priority_func=lambda x: x.build_priority())
        self.contexts_waiting = set()
        self.contexts_built = set()

        # store the full dependency graph of BuildContext instances
        # keys: a BuildContext
        # values: a list of BuildContext instances that require the key
        self.required_for = defaultdict(lambda: [])

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
        assert context_paths == self.built_paths

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

    def debug_short(self, submessage=False):
        logger.debug({'BuildState': {
            'len(self.contexts_unresolved)': len(self.contexts_unresolved),
            'len(self.contexts_buildable)': len(self.contexts_buildable.to_list()),
            'len(self.contexts_waiting)': len(self.contexts_waiting),
            'len(self.contexts_built)': len(self.contexts_built),
            }}, submessage=submessage)

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
        yaml_dict = {
            'built_paths': sorted([path for path in self.built_paths]),
            'buildable': [context.to_dict() for priority, context in self.contexts_buildable.to_list()],
            'waiting': [context.to_dict() for context in self.contexts_waiting],
            'unresolved': [context.to_dict() for  context in self.contexts_unresolved],
            }
        print(yaml.dump(yaml_dict, default_flow_style=False, sort_keys=False))

    def _add_context(self, context):
        '''
        A BuildContext object should rarely be added directly to one of the states.
        Instead, this method can be used to correctly place it.
        '''
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

    def is_done(self):
        return not any([
            len(self.contexts_unresolved) > 0,
            len(self.contexts_buildable) > 0,
            len(self.contexts_waiting) > 0,
            ])

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

    def build_all(self):
        with logger.make_subtree():
            # states will store a hash of BuildState at every iteration;
            # we will use this set to ensure that we don't get stuck in an infinite loop
            # repeating the same cycle of states forever;
            # in theory, this should not be needed,
            # and it is a sanity debug check to ensure our state transitions work correctly
            states = set()
            self.debug_print(f'iter={len(states)}')
            while not self.is_done():

                # perform all state transitions
                self.process_all_dependencies()
                self.debug_print(f'iter={len(states)} -- deps')
                self.assert_invariants()
                self.process_all_buildable()
                self.debug_print(f'iter={len(states)} -- build')
                self.assert_invariants()
                self.process_all_variable()
                self.debug_print(f'iter={len(states)} -- vars')
                self.assert_invariants()
                self.debug_print(f'iter={len(states) + 1}')

                # sanity infinite loop check
                state = self._state_hash()
                if state in states:
                    logger.error('duplicate state detected')
                    break
                states.add(state)


    ########################################
    # state transition methods
    ########################################

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
                        dependencies_built1.append(dep)
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
        context1 = context.model_copy(update={
            'dependencies_built': frozenset(dependencies_built1),
            'dependencies_building': frozenset(dependencies_building1),
            })
        self._add_context(context1)

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
        logger.info(f'building {path}')
        logger.info({'context': context.to_dict()}, submessage=True)
        self.contexts_built.add(context)
        if context.normalized_target not in self.targets_dict:
            pass
            #logger.info(f'target not in self.target_dicts, cannot build', submessage=True)
        else:
            future = build_context(context, self.targets_dict[context.normalized_target])
            asyncio.run(future)
        self.built_paths.add(path)
        return 1

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

                    # we can only resolve dependencies if:
                    # - they exactly match a target, or
                    # - they have all variables defined
                    dep_vars = extract_variables(dep['target'])
                    unmatched_vars = [
                            var for var in dep_vars if var not in context.variables_resolved
                            ]
                    if len(unmatched_vars) > 0 and dep['target'] not in self.targets_dict:
                        dependencies_unresolved1.append(dep)

                    # we can resolve the dependency
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

                            # FIXME: is this correct?
                            # if there is a $ in dep['target'],
                            # then we must match because we have previously checked
                            # that there are no unmatched variables
                            #assert len(matches) > 0

                        for normalized_target, target_env in matches:
                            # construct the new resolved variables;
                            # remove any variables not needed for target
                            target_variables = extract_variables(normalized_target)
                            variables_resolved = {**target_env, **context.variables_resolved}
                            for var in dict(variables_resolved):
                                if var not in target_variables:
                                    del variables_resolved[var]

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
                                    variables_resolved=variables_resolved,
                                    variables_unresolved=variables_unresolved,
                                    dependencies_built=[],
                                    dependencies_building=[],
                                    dependencies_unresolved=dependencies_unresolved,
                                    )
                            self.required_for[context1].append(context)
                            self._add_context(context1)

                            dep_paths = substitute_variables(normalized_target, target_env)
                            assert len(dep_paths) > 0
                            #assert all(['$' not in dep_path for dep_path in dep_paths])
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

            # process the next variable and process context
            var = next(iter(context.variables_unresolved))
            try:
                value = eval_var(
                        var,
                        context.variables_unresolved[var],
                        context.variables_resolved,
                        )
            except VariableEvaluationError:
                self._add_context(context)
                continue

            # NOTE:
            # the following if/for statement combo has confusing non-local effects;
            # if the variable is used in the target,
            # then we split the variable on newlines,
            # and we create a new context for each one of these split values;
            # this is what allows a single target to build many files;
            # but when we have a variable that is not included in the target,
            # we do not want to rebuild the same file with many different variable combinations
            # so we do not split the variable here (and do that elsewhere)
            if var in context.target_variables():
                value_list = value.split('\n')
            else:
                value_list = [raw_value]

            for val in value_list:

                # create new dictionaries for the resolved/unresolved variables;
                # then transfer the variable from unresolved to resolved;
                # note that we convert from frozendict to dict (making a copy)
                # so that we can edit the entries
                variables_resolved1 = dict(context.variables_resolved)
                variables_resolved1[var] = val

                variables_unresolved1 = dict(context.variables_unresolved)
                del variables_unresolved1[var]

                # generate the new context
                context1 = BuildContext(
                        normalized_target=context.normalized_target,
                        variables_resolved=variables_resolved1,
                        variables_unresolved=variables_unresolved1,
                        dependencies_built=context.dependencies_built,
                        dependencies_building=context.dependencies_building,
                        dependencies_unresolved=context.dependencies_unresolved,
                        )
                self.required_for[context1].append(context)
                self._add_context(context1)

@dataclass
class BuildSystem:
    # general settings
    project_dir: str = '.'
    config_file: str = 'fac.yaml'
    debug: bool = False
    trace: bool = False
    jobs: int = 1

    # build settings
    from_scratch: bool = False
    overwrite: bool = False
    build_postreqs: bool = False
    print_dependencies: bool = True
    print_prompt: bool = False
    validate_all: bool = False
    include_chat: str = None
    include_old: bool = False
    include_paths: list[str] = None
    options: list[str] = None
    auto_commit: bool = True
    allow_dirty: bool = False
    freeze: bool = False
    thaw: bool = False
    no_build: bool = False

    def __post_init__(self):
        self.target_dict = load_config('fac.yaml')
        self.registered_paths = []

        # load config file
        self.targets_dict = load_config(self.config_file)
        self.build_state = BuildState(self.targets_dict)

    def build_targets(self, targets: [str]):
        '''
        '''
        for target in targets:
            self.add_target(target)
        self.build_state.build_all()

    def add_target(self, target):
        matches = match_pattern_starstar(
                self.targets_dict.keys(),
                target,
                )
        for normalized_target, target_env in matches:
            variables_unresolved = copy.deepcopy(self.targets_dict[normalized_target]['variables'])
            for var in target_env:
                if var in variables_unresolved:
                    del variables_unresolved[var]
            context = BuildContext(
                    normalized_target=normalized_target,
                    variables_resolved=target_env,
                    variables_unresolved=variables_unresolved,
                    dependencies_built=[],
                    dependencies_building=[],
                    dependencies_unresolved=self.targets_dict[normalized_target]['dependencies'],
                    )
            self.build_state.required_for[context].append(None)
            self.build_state._add_context(context)


################################################################################

async def build_context(context, config):
    # create output directory if needed
    dirname = os.path.dirname(context.path())
    if len(dirname) > 0:
        os.makedirs(dirname, exist_ok=True)

    ########################################
    # build with shell
    ########################################

    if config.get('cmd'):
        process = await asyncio.create_subprocess_shell(
            config['cmd'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # merge stderr into stdout
            executable='/bin/bash',
            env=variable_dictionary_resolve({
                **os.environ,
                **context.variables_resolved,
                #'FAC_DEPENDENCIES': '\n'.join(sorted(context.dependency_paths)),
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
                env=variable_dictionary_resolve({
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
            prompt_description += '\n</file_description>'
        except TemplateProcessingError as e:
            raise FACError()

        prompt_description += '\n'
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

        # `format_cmd` defines the output format
        format_cmd = ''
        if 'md' not in extension and 'markdown' not in extension:
            format_cmd += 'Do not output markdown, and do not put the output inside a codeblock.'
        else:
            format_cmd += 'Use markdown formatting to structure the output.'

        if extension == '.json':
            format_cmd += 'Output JSON.'
            response_format = {'type': 'json_object'}
        elif extension == '.jsonl':
            response_format = {'type': 'json_object'}
            format_cmd += f'Output JSONL.  Each line of the output should be a single JSON object. There should be at most {self.global_settings["jsonl_num_lines"]} total lines.'
            format_cmd = process_template(format_cmd, env_vars=context.variables)

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
            format_cmd += json.dumps(schema, indent=2).strip()
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
            format_cmd += ' Ensure the output conforms to the following JSON schema:\n'
            #format_cmd += text.strip()
            format_cmd += json.dumps(schema, indent=2).strip()
            schema['additionalProperties'] = False
            response_format = {
                'type': 'json_schema',
                'json_schema': {
                    'strict': True,
                    'name': 'fac_json_schema',
                    'schema': schema,
                    },
                }

        format_cmd = '\n<formatting>\n' + format_cmd + '\n</formatting>'

        # add the user role + message
        message = {
            'role': 'user',
            'content': [{ 'type': 'text', 'text': prompt + format_cmd}]
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
        logger.error(f'Failed to evaluate variable {var}')
        lines = expr.split('\n')
        if len(lines) == 1:
            logger.error(f'build command: {expr}', submessage=True)
        else:
            logger.error(f'build command:', submessage=True)
            for line in lines:
                logger.error(line, submessage=True)
        for line in (cmd.stderr.strip() + '\n' + cmd.stdout).strip().split('\n'):
            logger.error(line, submessage=True)
        logger.error('env:', submessage=True)
        for var in env:
            logger.error(f' - {var}: "{env[var].replace("\n", "\\n")}"', submessage=True)
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
        errorstrs = [
            f'error evaluating {var}=$({expr})',
            f'context={context}',
            f"result.returncode={result.returncode}",
            f"result.stdout={result.stdout}",
            f"result.stderr={result.stderr}",
            ]
        super().__init__('\n'.join(errorstrs))

