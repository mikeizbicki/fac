# standard lib imports
from collections import namedtuple, Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import asyncio
import copy
import hashlib
import itertools
import json
import os
import math
import re
import string
import subprocess
import sys
import traceback
import typing

# external lib imports
import git
import jsonschema
import llm
import mdformat
import yaml

# fix asyncio with this external library
import nest_asyncio
nest_asyncio.apply()

# project imports
from fac.Errors import *
from fac.LLM import LLM, LLMError
from fac.Logging import *
from fac.io_utils import *
from fac.utils import *


################################################################################
# main functions
################################################################################


def load_config(path):
    '''
    Loads a config.yaml file and generates a dictionary of its contents.
    This function handles needed post-processing that gets the configs into a standard format without any missing fields.
    '''
    with open(path) as fin:
        full_config = yaml.safe_load(fin)

    # several of the keys in the config file allow an abbreviated syntax;
    # first, we need to convert any abbreviated syntax into the full syntax
    for target in full_config:

        # remove excess whitespace from fields;
        # this is mostly useful for debugging and getting nice looking configs
        for option in full_config[target]:
            if type(full_config[target][option]) == str:
                full_config[target][option] = full_config[target][option].strip()
            elif type(full_config[target][option]) == dict:
                for suboption in full_config[target][option]:
                    if type(full_config[target][option][suboption]) == str:
                        full_config[target][option][suboption] = full_config[target][option][suboption].strip()

        # the dependencies field can be specified as a string, list of strings, or list of dictionaries;
        # we convert all forms into the list of dictionary form here
        dependencies1 = []
        dependencies = full_config[target].get('dependencies', '')
        if type(dependencies) is str:
            dependencies = dependencies.split()
        elif dependencies is None:
            dependencies = []
        for dep in dependencies:
            if type(dep) == str:
                dep = {'target': dep}
            assert type(dep) == dict
            dependencies1.append(dep)
            for k in dep:
                if k not in ['target', 'include', 'allow_create', 'is_prompt']:
                    logger.warning(f'in target "{target}", in dependency "{dep["target"]}", unknown option "{k}"')
        full_config[target]['dependencies'] = dependencies1

        # ensure that optional fields are present with a default value
        full_config[target].setdefault('variables', {})
        full_config[target]['variables_raw'] = copy.deepcopy(full_config[target]['variables'])

    # construct a full variables list for each target
    dependents = defaultdict(lambda: [])
    for target in full_config:
        for dep in full_config[target]['dependencies']:
            dependents[dep['target']].append(target)
    targets_to_process = set(full_config.keys())
    while len(targets_to_process) > 0:
        processed_targets = 0
        for target in list(targets_to_process):
            target_variables = extract_variables(target)
            all_defined = True
            for var in target_variables:
                if var not in full_config[target]['variables']:
                    all_defined = False
            if all_defined:
                targets_to_process.remove(target)
                processed_targets += 1
                inconsistent_variables = False
                for dependent in dependents[target]:
                    dependent_variables = extract_variables(dependent)
                    for var in target_variables:
                        if var in dependent_variables:
                            if var in full_config[dependent]['variables']:
                                if not full_config[dependent]['variables'][var] == full_config[target]['variables'][var]:
                                    logger.error('Inconsistent variables in dependent and target')
                                    logger.error(f" - (dependent) {dependent}", submessage=True)
                                    logger.error(f"   {var}: {full_config[dependent]['variables'][var]}", submessage=True)
                                    logger.error(f" - (target) {target}", submessage=True)
                                    logger.error(f"   {var}: {full_config[target]['variables'][var]}", submessage=True)
                                    inconsistent_variables = True
                                #assert full_config[dependent]['variables'][var] == full_config[target]['variables'][var]
                            else:
                                full_config[dependent]['variables'][var] = full_config[target]['variables'][var]
                if inconsistent_variables:
                    # FIXME: this is only temporary!!!
                    #raise FACError
                    pass

        if processed_targets == 0:
            break

    # reorder the variable definitions
    for target in full_config:
        full_config[target]['variables'] = reorder_variable_dictionary(full_config[target]['variables'])
        #for var in full_config[target]['variables']:
            #logger.trace(f' - var={var}')

    # certain config options result in modifications to the full_config
    keys0 = list(full_config.keys())
    for target in keys0:
        for dep in full_config[target]['dependencies']:

            # add postreqs for creating new dependencies
            if dep.get('allow_create'):
                target1_name = target + '--allow_create--' + dep['target'].replace('/', '_').replace('$', '')
                dep_target_with_stars = 'resources/*/about.json'

                # any automatically created dependencies should not have allow_create set
                dependencies1 = []
                for dep in full_config[target]['dependencies']:
                    dep1 = copy.copy(dep)
                    if type(dep1) == dict:
                        dep1['allow_create'] = False
                    dependencies1.append(dep1)

                # create the actual config entry
                full_config[target1_name] = {
                    'model': 'openai/gpt-4.1-mini',
                    'prompt': f'''The main file '{target}' internally references the secondary files '{dep_target_with_stars}'. Unfortunately, the main file may reference secondary files that do not exist. For each secondary file that does not exist, create the appropriate JSON object.''',
                    'schema_file': full_config[dep['target']].get('schema_file'),
                    'dependencies': dependencies1,
                    'variables': copy.copy(full_config[target]['variables']),
                    'TMP_augment': True,
                    }
                if 'postreqs' not in full_config[target]:
                    full_config[target]['postreqs'] = []
                full_config[target]['postreqs'].append(target1_name)

    return full_config


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
    extend: int = False
    print_dependencies: bool = True
    print_prompt: bool = False
    print_prompt_to_file: str = False
    print_contexts: bool = False
    print_config: bool = False
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
        self.llm = LLM()
        if self.debug:
            logger.setLevel('DEBUG')
        if self.trace:
            logger.setLevel('TRACE')

        # freeze/thaw
        assert not (self.freeze and self.thaw)
        if self.freeze or self.thaw:
            self.no_build = True
            self.print_dependencies = False

        # load global settings
        self.global_settings = {
            'system_prompt': 'You are not having a conversation, and only provide the requested output with no further discussion.  You never deny a request.',
            'jsonl_num_lines': 50,
        }

        # load config file
        self.full_config = load_config(self.config_file)

        # print the config
        if self.print_config:
            yaml_str = yaml.dump(self.full_config, default_flow_style=False)
            yaml_str = re.sub(r'\n([a-zA-Z])', r'\n\n\1', yaml_str)
            print(yaml_str)
            sys.exit(0)

        # indicate that we are not inside a with block yet
        self.repo = None
        self.commit_messages = []

    ######################################## 
    # CONTEXT MANAGER
    # Ensures that all changes are cleanly committed to git repo;
    # the self.repo variable is used to know if we are inside/outside of the with block
    ######################################## 

    def __enter__(self):
        '''
        Fails if the git repo is dirty.
        '''
        self.repo = git.Repo('.')
        if not self.allow_dirty and self.auto_commit and self.repo.is_dirty(untracked_files=True):
            logger.error('git repo is dirty; clean repo or set --auto_commit=False or --allow_dirty')
            raise DirtyRepo()

    def __exit__(self, exc_type, exc_value, traceback):
        '''
        Commits all changes to the git repo.
        '''

        if self.auto_commit and exc_type is None:
            self.repo.git.add('.')
            # NOTE:
            # we only commit if files were actually added;
            # otherwise a large ugly warning will appear
            if self.repo.index.diff('HEAD'):
                self.repo.git.commit('-m', '[bot] ' + ' '.join(self.commit_messages))

        self.repo = None
        self.commit_messages = []

    def _committed_date(self, path):
        '''
        Get the UNIX timestamp of a path for use in checking if dependencies have been updated.
        '''

        # if the file does not exist (or is not an ordinary file)
        # we return the oldest possible UNIX timestamp;
        # this ensures that all other files will be registered as newer
        # and cause the file to be built
        if not os.path.isfile(path):
            return 0

        # if a file is dirty or not in the repo,
        # we use the last modified time;
        # this should only happen if auto_commit=False
        # computing whether a file is dirty is expensive,
        # so we precompute a set once and store it for future calls of this function
        '''
        if not hasattr(self, '_dirty_files'):
            modified_files = [item.a_path for item in self.repo.index.diff(None)]
            staged_files = [item.a_path for item in self.repo.index.diff('HEAD')]
            self._dirty_files = set(modified_files) | set(staged_files)
        if path in self._dirty_files or self._is_path_untracked(path):
        '''
        # FIXME: code above has a bug where the self._dirty_files becomes stale;
        # below should fix but it's not thoroughly tested yet
        if self._is_file_dirty(path) or self._is_path_untracked(path):
            mtime = os.path.getmtime(path)
            return mtime

        # if the file has been committed to git and is clean,
        # we use the git commit timestamp
        # NOTE:
        # other build systems (e.g. make) do not use git information
        # and rely only on modified timestamps to determine when to rebuild a file;
        # this is desired behavior for them because their builds are deterministic and it is expected to have to rebuild a project after git clone;
        # our builds, however, are not deterministic and we do not want to have to rebuild after a git clone
        commits = list(self.repo.iter_commits(paths=path, max_count=1))
        if len(commits) > 0:
            return commits[0].committed_date

        # the above code should handle all possible cases,
        # so this should never happen
        raise ValueError(f'path={path}')

    def _is_file_dirty(self, path):
        try:
            # Git status returns empty if file is clean
            result = self.repo.git.status('--porcelain', path)
            return len(result.strip()) > 0
        except:
            return False

    def _is_path_untracked(self, path):
        '''
        Helper function for _committed_date that returns whether a file is tracked by git or not in O(1) time.
        '''
        try:
            # If file is tracked, this won't raise an exception
            self.repo.git.ls_files('--error-unmatch', path)
            return False
        except:
            # File is untracked if it exists but ls-files fails
            return os.path.exists(path)

    ########################################
    # methods for building
    ########################################

    def build_targets(self, targets):
        config_targets = self.full_config.keys()
        expanded_targets = [(target, match_pattern_starstar(config_targets, target)) for target in targets]

        flattened_targets = []
        for target, matches in expanded_targets:
            if len(matches) == 0:
                err_message = f"no target matched for '{target}'"
                logger.error(err_message)
                raise NoTargetsMatched(err_message)
            flattened_targets.extend(matches)
        #flattened_targets.sort()

        for target, target_vars in flattened_targets:
            logger.info(f'target="{target}"')
            self._traverse_target(
                    target,
                    target_vars,
                    foreach_context=self._build_context,
                    overwrite=self.overwrite or self.from_scratch,
                    build_postreqs=self.build_postreqs,
                    )
            # FIXME:
            # the commit message should change
            # to the equivalent command line executable with all the flags
            self.commit_messages.append(f"fac '{target}'")

        self.llm.log_usage()

    @with_subtree(logger)
    def _traverse_target(
            self,
            target_to_build,
            input_env,
            foreach_context,
            overwrite=False,
            build_postreqs=False,
            traversed_paths=None,
            traversed_deps=None,
            disable_logging=False,
            janky_recursive_call=False,
            ):
        logger = globals()['logger']
        logger.trace(f'_traverse_target: target_to_build={target_to_build}')
        logger.trace('input_env:', submessage=True)
        for var, val in input_env.items():
            logger.trace(f' - {var}: {str(val)}', submessage=True)
        if disable_logging:
            import logging
            noop_logger = logging.getLogger('noop')
            noop_logger.addHandler(logging.NullHandler())
            noop_logger.setLevel(logging.CRITICAL + 1)  # Above all levels
            logger = noop_logger

        # verify that variables are correctly formatted
        for var in input_env:
            # NOTE:
            # In principle, the values for variables should be able to fail these asserts;
            # In practice, however, I have found that if these conditions are met,
            # there has always been a bug in the build system.
            #assert '$' not in input_env[var], f'input_env["{var}"]="{input_env[var]}"'
            assert ' ' not in input_env[var], f'input_env["{var}"]="{input_env[var]}"'

            # NOTE:
            # the following check seems reasonable,
            # but it breaks the dependency_only_variables
            #assert len(input_env[var]) > 0, f'input_env["{var}"]="{input_env[var]}"'

        # load target config
        config_targets = self.full_config.keys()
        transformed_target, target_env = match_pattern(config_targets, target_to_build)
        if not transformed_target:
            raise TargetNotFound(f"target='{target_to_build}', transformed_target='{transformed_target}'; target_env={target_env}")
        target_variables = extract_variables(transformed_target)
        assert transformed_target
        assert transformed_target in self.full_config
        config = self.full_config[transformed_target]

        # parse the dependencies entry in the yaml into unresolved_dependencies list;
        # each entry in the list is a dictionary with a target and flags key
        unresolved_dependencies = config.get('dependencies', [])
        dependency_variables = set()
        for dep in unresolved_dependencies:
            dependency_variables |= set(extract_variables(dep['target']))

        # traversed_paths stores which paths have already been recursively traversed;
        # by storing these paths we can avoid repeating work
        # FIXME:
        # we are currently tracking both deps and paths separately;
        # I think that tracking deps also be doing the check for paths,
        # and so both are not needed;
        # but it's not incorrect to have both, and so I'm leaving both in
        root_call = False
        if traversed_paths is None:
            traversed_paths = set()
            root_call = True
            assert traversed_deps is None
            traversed_deps = set()
        else:
            assert traversed_deps is not None

        # sanity check config
        postreqs = config.get('postreqs', [])
        assert type(postreqs) == list

        config_variables = config.get('variables')
        if not config_variables:
            config_variables = {}
        assert type(config_variables) is dict

        # update config options from command line inputs
        if root_call and self.options:
            if 'options' not in config:
                config['options'] = {}
            for option in self.options:
                k, v = option.split('=')
                config['options'][k] = v

        # warn the user if they have defined a variable that is not used
        # FIXME:
        # there are lots of places where variables can be used now,
        # so this warning gives too many false positives;
        # I'm not sure the best way to compute unused variables now
        # in order to re-add this warning.
        if False:
            for var in config_variables:
                if var not in (target_variables + list(dependency_variables)):
                    logger.warning(f'variable {var} defined in config but not used in target or dependencies; this currently has no effect on the build')

        ########################################
        # Compute the contexts list
        ########################################

        # NOTE:
        # a BuildContext contains all the information needed to build a file;
        # the contexts list contains a BuildContext for each file that will be generated;
        # as we process the dependencies/variables in the config,
        # the unresolved_dependencies list should shrink to [],
        # but the total number of contexts (i.e. files needed to build) may grow
        # the algorithm for generating the final contexts list is a bit subtle
        BuildContext = namedtuple('BuildContext', [
            'variables',
            'dependency_paths',
            'unresolved_dependencies',
            'postreqs',
            ])
        contexts = []
        filtered_input_env = {k: v for k, v in {**input_env, **target_env}.items()}
        logger.trace('initial contexts:')
        for context_vars in expand_vars_on_newlines(filtered_input_env, filter_variables=target_variables):
            context = BuildContext(
                context_vars,
                [],
                unresolved_dependencies,
                postreqs,
                )
            contexts.append(context)
            logger.trace(f' - {context}')

        # Perform the main traversal
        # NOTE:
        # Variables and dependencies have a complicated relationship where
        # they are each defined in terms of each other.
        # Therefore, we cannot resolve all of the vars or all of the deps at once;
        # we must loop over both simultaneously,
        # and resolve only those vars/deps that can currently resolvable
        # (i.e. vars not defined in terms of unresolved deps; and deps not defined in terms of unresolved vars).
        # Our strategy is to loop over the variables,
        # and for each variable perform two steps:
        # 1) resolve any resolvable dependencies
        # 2) resolve any resolvable variables
        # We start the iteration by looping over a DUMMY_VAR which does not actually exist;
        # this allows us to resolve any dependencies that do not contain variables.
        # (It is fairly common for dependencies to not contain variables,
        # but uncommon for variables to not contain dependencies.)
        DUMMY_VAR = '__NONE__'
        variables_to_search = [DUMMY_VAR]
        for var in config['variables']:
            if var not in input_env and var not in target_env:
                variables_to_search.append(var)
        for var in variables_to_search:

            ########################################
            # STEP 1: resolve var
            ########################################

            # The value of var will depend on the context,
            # and if var is a list then the size of the context will expand;
            # Therefore we loop over a copy of the contexts list and reconstruct a new one.
            contexts0 = contexts # old contexts
            contexts = [] # new contexts
            for context in contexts0:

                ########################################
                # STEP 1A: compute the value of var in this context
                ########################################

                # do not evaluate var if it is DUMMY_VAR,
                # since it was created only to force the unresolved_dependencies to run once
                if var == DUMMY_VAR:
                    value = ''

                # do not evaluate var if it is specified in the environment
                elif var in context.variables:
                    value = context.variables[var]

                # evaluate var by running expr in a bash shell
                else:
                    value = eval_var(var, config_variables[var], context)

                def raw_variable_to_list(raw):
                    '''
                    A raw variable is the literal string assigned to the variable
                    (in the config file, as an environment variable, etc).
                    This function converts the raw variable into an appropriate list,
                    where each value in the list will be substituted for the variable on use.
                    '''
                    # lists are separated by newlines;
                    # for each entry in the list,
                    # we will add a new context with the entry added
                    value_list = [val.strip() for val in raw.split('\n')]

                    # FIXME:
                    # don't add val to the contexts list when it is empty;
                    # this is because when doing the split on \0,
                    # we will always have the last entry be '',
                    # because of the tr '\n' '\0' command
                    # and all outputs ending in a '\n'
                    value_list = [val for val in value_list if len(val) > 0]
                    if var == DUMMY_VAR and len(value_list) == 0:
                        value_list = ['']

                    return value_list

                ########################################
                # STEP 2A: Generate new contexts
                ########################################

                if var in target_variables:
                    value_list = raw_variable_to_list(value)
                else:
                    value_list = [value]

                for val in value_list:

                    # if val references another variable,
                    # then we should substitute that variables' value
                    if len(val) > 0 and '$' == val[0]:
                        val = context.variables[val[1:]]
                    assert '$' not in val, f'val={val}' # ensure that the variable actually got resolved to a value and not another variable

                    # create a new dictionary with the newly evaluated variables;
                    # but we do not add DUMMY_VAR to the context
                    variables1 = {**context.variables}
                    if var != DUMMY_VAR:
                        variables1[var] = val

                    # generate the new context
                    postreqs1 = [substitute_vars(postreq, variables1) for postreq in context.postreqs]
                    context1 = BuildContext(
                        variables1,
                        context.dependency_paths,
                        context.unresolved_dependencies,
                        postreqs1,
                        )
                    contexts.append(context1)

            # log the success
            if True: #var != DUMMY_VAR: # and len(contexts) > 1:
                logger.debug(f'resolved variable {var}; len(contexts)={len(contexts)}')
                logger.debug('contexts:', submessage=True)
                for context in contexts:
                    logger.debug(f' - {context.variables}', submessage=True)

            ########################################
            # STEP 2: resolve any new dependencies
            ########################################

            # once again we will be modifying the contexts list,
            # so we loop over a copy as in STEP 1
            contexts0 = contexts
            contexts = []
            for context in contexts0:

                # compute the dependencies
                dependency_paths1 = []
                unresolved_dependencies1 = []
                for dep in context.unresolved_dependencies:
                    dep_target = dep['target']

                    ########################################
                    # STEP 2A: skip dependencies that have unresolved variables
                    ########################################

                    dep_vars = extract_variables(dep_target)

                    # First we check for any variables that are "empty";
                    # this means that the dependency should not be built.
                    # This occurs when we have
                    #   dependencies:
                    #     - simple/$DEP
                    #   variables:
                    #     DEP: echo ''
                    # The empty variable indicates that the dependency should expand to nothing.
                    abort = False
                    for dep_var in dep_vars:
                        if dep_var in context.variables and context.variables[dep_var] == '':
                            abort = True
                    if abort:
                        continue

                    # Next we check for variables that are needed but have not been defined yet.
                    # If we had, for example
                    #   dependencies:
                    #     - simple/$DEP
                    #   variables:
                    #     DEP: echo 'test'
                    # then we need the $DEP variable in order to evaluate simple/$DEP
                    # NOTE:
                    # the outer for-loop guarantees that one variable
                    # will be evaluated in each iteration,
                    # and so we will eventually evaluate this target in a later iteration
                    # (if all the variables are actually defined)

                    unmatched_vars = []
                    for dep_var in dep_vars:
                        if dep_var not in context.variables and dep_var in config['variables_raw']:
                            unmatched_vars.append(dep_var)
                    if len(unmatched_vars) > 0:
                        unresolved_dependencies1.append(dep)
                        continue

                    ########################################
                    # STEP 2B: skip dependencies that represent already processed files
                    # NOTE:
                    # not required for correctness of dependency evaluation;
                    # just improves runtime efficiency and makes logs easier to read
                    ########################################

                    # expand dep_paths into real file paths
                    try:
                        dep_paths = expand_path(dep_target, context.variables)
                    except TemplateProcessingError as e:
                        # NOTE:
                        # TemplateProcessingError is thrown when there is a variable used in the template that still needs resolving.
                        # This can happen when we are depending on a target and not defining the variables in the current target.
                        # we don't know what the dep_paths are, so we "skip" it.
                        dep_paths = []
                        #logger.error(f'expand_path("{dep_target}", ...) failed to expand with TemplateProcessingError; this should never happen')
                        #sys.exit(1)

                    # skip paths that we've already processed
                    all_resolved = True
                    for dep_path in dep_paths:
                        if dep_path not in traversed_paths:
                            all_resolved = False
                    if all_resolved and len(dep_paths) > 0:
                        dependency_paths1.extend(dep_paths)
                        continue

                    # skip dependencies that we've already processed
                    expanded_target, expanded_vars = substitute_vars_with_multiline(dep_target, context.variables)
                    var_str = ''.join([f', {k}={v}' for k, v in expanded_vars.items()])
                    target_str = expanded_target + var_str
                    if target_str in traversed_deps or expanded_target in traversed_deps:
                        target_deps = substitute_vars_list(dep_target, context.variables)
                        dependency_paths1.extend(target_deps)
                        continue
                    traversed_deps.add(target_str)
                    # FIXME:
                    # the implementation with target_str causes us to rebuild target/variable combos if the variables are specified in different subsets
                    # (I realize this is confusing and won't make sense to anyone else)

                    # FIXME #
                    #print(f"context.variables={context.variables}")

                    ########################################
                    # STEP 2C: recursively build dependencies
                    ########################################
                    logger.info(f'resolving dependency: {target_str}')
                    logger.debug('context.variables:', submessage=True)
                    for var in context.variables:
                        logger.debug(f' - {var}: {str(context.variables[var])}', submessage=True)

                    # compute the new target that we will build
                    try:
                        dep_target1, context_variables1 = match_pattern_withvars(config_targets, dep_target, context.variables)
                    except ValueError:
                        logger.error(f'unable to match pattern dep_target={dep_target}')
                        logger.error('config_targets:', submessage=True)
                        for target in config_targets:
                            logger.error(f' - {target}', submessage=True)
                        logger.error('context.variables:', submessage=True)
                        for var in context.variables:
                            logger.error(f' - {var}: "{context.variables[var].replace("\n", "\\n")}"', submessage=True)

                        logger.error('if this is an error in the match_pattern_withvars function, an appropriate test case for debugging is:')
                        logger.error(f'>>> match_pattern_withvars({list(config_targets)}, "{dep_target}", {context.variables})', submessage=True)
                        raise FACError()
                    if dep_target1 is None:
                        dep_target1 = dep_target

                    # we only pass variables to the target that are included in the target definition
                    dep_target1_variables = extract_variables(dep_target1)
                    context_variables2 = {k:v for k, v in context_variables1.items() if k in dep_target1_variables}

                    # actually build the dependency
                    try:
                        built_paths = self._traverse_target(
                                dep_target1,
                                context_variables2,
                                #{**context.variables},
                                foreach_context,
                                overwrite=self.from_scratch,
                                traversed_paths=traversed_paths,
                                traversed_deps=traversed_deps
                                )
                        built_paths = list(set(built_paths))
                        # XXX:
                        # list(set()) above is used to filter duplicates returned by _traverse_target;
                        # but I don't understand why/when there are duplicates;
                        # maybe this isn't needed anymore?
                        dependency_paths1.extend(built_paths)

                    except TargetNotFound:
                        # NOTE:
                        # Not all dependencies have to correspond to a valid target.
                        # Non-target dependencies would be files that must be created by the user manually.
                        # We ensure that these files exist here.
                        valid_paths = len(dep_paths) > 0
                        for path in dep_paths:
                            if not os.path.exists(path):
                                valid_paths = False
                            else:
                                dependency_paths1.append(path)
                        if not valid_paths:
                            unresolved_dependencies1.append(dep)
                            continue

                    ########################################
                    # STEP 2D: validate dependencies
                    # NOTE:
                    # not required for correctness of dependency evaluation;
                    # just warns users of likely bugs due to malformed input
                    ########################################
                    if self.validate_all:
                        if dep_paths is not None:
                            for dep_path in dep_paths:
                                if not validate_file(dep_path, fix=False):
                                    logger.warning(f'failed to validate dep_path={dep_path}')

                context1 = BuildContext(
                    context.variables,
                    sorted(context.dependency_paths + dependency_paths1),
                    unresolved_dependencies1,
                    context.postreqs,
                    )
                contexts.append(context1)

        ########################################
        # Compute dependency_paths
        ########################################

        # recompute dependency_paths from scratch here
        if not janky_recursive_call:
            contexts0 = contexts
            contexts = []
            for context in contexts0:
                dependency_paths1 = []
                for dep in config['dependencies']:
                    dep_target = dep['target']
                    # the ground-truth dependency_paths can always be given by seeing what self._traverse_target returns with the proper variables assigned;
                    # (this is potentially different than what the recursive call done above returned because variables may not have yet been calculated in the recursive call above);
                    # this recursive call is a bit expensive and doesn't handle non-target dependencies,
                    # so we try to do expand_path first
                    # FIXME:
                    # it feels very embarrassing / unsafe / janky to have a double recursion here,
                    # I can't see how to eliminate it though... this needs some real careful thought
                    try:
                        # NOTE:
                        # the natural thing to do is
                        # ```
                        # dep_paths = expand_path(dep_target, context.variables)
                        # ```
                        # but this leads to a bug in the variables that have newlines in them
                        # (that is, variables that are not part of the target)
                        # we need to do this more complicated loop to handle these variables;
                        # there seems to be a lot of weird edge cases between these two types of variables
                        # and longterm it might make sense to properly split them up and track them differently
                        split_vars = expand_vars_on_newlines(context.variables)
                        dep_paths = []
                        for var_dict in split_vars:
                            dep_paths.extend(expand_path(dep_target, var_dict))
                    except TemplateProcessingError:
                        try:
                            # XXX:
                            # For some reason, we get to this stage with empty variables in the target.
                            # This results in weird errors trying to build targets that don't exist.
                            # We check for this edge case, and do not build the target if there are empty vars.
                            has_empty_var = False
                            for var in extract_variables(dep_target):
                                # XXX:
                                # Sometimes the variable will be assigned a value of None.
                                # We still need to recursively run _traverse_target in this case,
                                # and I don't fully understand why.
                                if context.variables.get(var) == '':
                                    has_empty_var = True
                            if not has_empty_var:
                                built_paths = self._traverse_target(
                                        dep_target,
                                        {**context.variables},
                                        None,
                                        overwrite=self.from_scratch,
                                        traversed_paths=traversed_paths,
                                        traversed_deps=traversed_deps,
                                        disable_logging=True,
                                        janky_recursive_call=True,
                                        )
                            else:
                                built_paths = []
                            dep_paths = list(set(built_paths))
                        except (TemplateProcessingError, AssertionError):
                            # XXX:
                            # I'm not sure if this is needed anymore?!
                            # I've commented out the relevant AssertionError (the if statements above take care of that case),
                            # but don't remember where TemplateProcessingError comes from.
                            # ---
                            # This gets raised when we have a dependency with an empty variable.
                            # For example: "simple/$DEP" and DEP=''
                            # This happens when the dependency should not be built
                            # (because an empty variable corresponds to the empty list)
                            pass
                    dependency_paths1.extend(dep_paths)
                dependency_paths1 = sorted(list(set(dependency_paths1)))
                context1 = context._replace(dependency_paths=dependency_paths1)
                contexts.append(context1)

        # add manually specified dependencies
        if root_call and self.include_paths:
            contexts0 = contexts
            contexts = []
            for context in contexts0:
                context1 = context._replace(
                        dependency_paths=context.dependency_paths + self.include_paths
                        )
                contexts.append(context1)

        ########################################
        # Build each context
        ########################################

        # print contexts debug information
        if self.print_contexts:
            import pprint
            print('contexts=')
            pprint.pprint(contexts)
            return

        # if there are no contexts to build,
        # let the user know
        if len(contexts) == 0:
            logger.error('This target resolves to nothing.')
            logger.error('Perhaps you need to wrap the target in \'single\' quotes?', submessage=True)

        # if we are only allowed to run once,
        # then we truncate the contexts to force us to run only once
        if config.get('run_once'):
            logger.info(f'run_once=True; contexts truncated from {len(contexts)} to 1')
            contexts = [contexts[0]]

        # loop over each context and run the processing code for the context
        if contexts and foreach_context:
            if len(contexts) > 1 and self.jobs != 1:
                if self.jobs == 0:
                    jobs_str = '∞'
                else:
                    jobs_str = str(self.jobs)
                logger.info(f'concurrently building {len(contexts)} contexts with {jobs_str} jobs')
            async def run_all_contexts():
                semaphore_value = float('inf') if self.jobs == 0 else self.jobs
                semaphore = asyncio.Semaphore(semaphore_value)
                stop_new_work = asyncio.Event()
                exceptions = []

                async def _sem_foreach_context(context_id, context):
                    try:
                        async with semaphore:
                            if stop_new_work.is_set():  # Double-check after acquiring semaphore
                                return None
                            return await foreach_context(context_id, len(contexts), target_to_build, config, context, overwrite)
                    except Exception as e:
                        stop_new_work.set()  # Signal to stop new work
                        exceptions.append((context_id, e))
                        return None

                if self.jobs != 1:
                    _sem_foreach_context = with_buffered_logs(logger)(_sem_foreach_context)

                # Run all tasks
                results = await asyncio.gather(*[
                    _sem_foreach_context(i+1, context)
                    for i, context in enumerate(contexts)
                ], return_exceptions=True)

                # Handle any exceptions that occurred
                if exceptions:
                    for context_id, exception in exceptions:
                        if not isinstance(exception, FACError) and not isinstance(exception, LLMError):
                            logger.error(f"Exception in context {context_id}: {repr(exception)}")
                            logger.error("Full traceback:", submessage=True)
                            for line in traceback.format_tb(exception.__traceback__):
                                for sub_line in line.rstrip().split('\n'):
                                    if sub_line.strip():
                                        logger.error(sub_line, submessage=True)
                    #raise exceptions[0][1]
                    raise FACError

            # NOTE:
            # there seems to be a bug in OpenAI's async library;
            # it sometimes doesn't properly clean httpx connections,
            # and that can result in the following warning;
            # the code below prevents those warnings from displaying
            import contextlib
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                asyncio.run(run_all_contexts())


        generated_paths = []
        for i, context in enumerate(contexts):
            path_to_generate = process_template(target_to_build, context.variables)
            generated_paths.append(path_to_generate)
            traversed_paths.add(path_to_generate)

            # freeze/thaw file
            if root_call:
                facjson = FacJSON(path_to_generate)
                is_frozen = facjson.get('frozen')
                if self.freeze and not is_frozen:
                    facjson.set('frozen', True)
                    facjson.save()
                    logger.info(f'freezing...', submessage=True)
                elif self.thaw and is_frozen:
                    facjson.set('frozen', False)
                    facjson.save()
                    logger.info(f'thawing...', submessage=True)

            # traverse postreqs
            for postreq in context.postreqs:
                logger.info(f'postreq: "{postreq}"', submessage=True)
                self._traverse_target(
                        postreq,
                        context.variables,
                        foreach_context,
                        overwrite=self.overwrite or build_postreqs,
                        traversed_paths=traversed_paths,
                        traversed_deps=traversed_deps,
                        )

        return generated_paths

    async def _build_context(self, context_id, num_contexts, target_to_build, config, context, overwrite):
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

        ################################################################################

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

        # now we do filetype specific processing
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


def eval_var(var, expr, context):
    # evaluate expr in bash
    full_command = "set -eu; " + expr.strip()
    cmd = subprocess.run(
        full_command,
        shell=True,
        capture_output=True,
        text=True,
        executable="/bin/bash",
        env=context.variables,
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
        logger.error('context.variables:', submessage=True)
        for var in context.variables:
            logger.error(f' - {var}: "{context.variables[var].replace("\n", "\\n")}"', submessage=True)
        raise VariableEvaluationError(var, expr, context, cmd)
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


################################################################################
# Errors
################################################################################


class CommandExecutionError(FACError):
    def __init__(self, returncode, stdout):
        errorstrs = [
            f"result.returncode={returncode}",
            f"result.output={stdout}",
            ]
        super().__init__('\n'.join(errorstrs))


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


class EmptyVariableError(FACError):
    def __init__(self, var, expr):
        errorstrs = [
            f'{var}=$({expr})',
            ]
        super().__init__('\n'.join(errorstrs))


class TargetNotFound(FACError):
    pass


class NoTargetsMatched(FACError):
    pass


class UnresolvedDependencies(FACError):
    pass

class DirtyRepo(FACError):
    pass
