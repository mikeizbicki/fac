# standard lib imports
from collections import namedtuple, Counter
from datetime import datetime
from dataclasses import dataclass
import copy
import itertools
import json
import os
import math
import string
import subprocess
import sys
import typing

# external lib imports
import git
import jsonschema
import llm
import mdformat
import yaml

# project imports
from fac.Logging import logger, with_subtree
from fac.LLM import LLM
from fac.utils import *


def validate_file(path, schema_file=None, fix=False):
    _, extension = os.path.splitext(path)

    # ensure the input path exists
    if not os.path.exists(path):
        logger.warning(f'path="{path}" does not exist, cannot validate')
        return False

    # ensure the file is non-empty
    elif not path.startswith('/dev/') and os.path.getsize(path) == 0:
        logger.warning(f'os.path.getsize("{path}")=0')

    # validate JSON files
    elif extension == '.json':

        # ensure that the JSON can be parsed
        with open(path) as fin:
            text = fin.read()
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            if fix:
                logger.info(f'fixing JSONDecodeError in path={path}')
                import json_repair
                with open(path, 'wt') as fout:
                    obj = json_repair.loads(text, skip_json_loads=True)
                    json.dump(obj, fout)
            else:
                raise e

        # verify that the JSON matches the schema
        if schema_file:
            logger.trace(f'verifying that "{path}" satisfies schema "{schema_file}"')
            with open(path) as fin:
                data = json.load(fin)
            with open(schema_file) as fin:
                schema = json.load(fin)
                jsonschema.validate(instance=data, schema=schema)

        # reformat with pretty indentation
        if fix:
            logger.info('fixing JSON indentation')
            with open(path, 'r') as fin:
                data = json.load(fin)
            with open(path, 'w', encoding='utf-8') as fout:
                json.dump(data, fout, indent=4, ensure_ascii=False)

    # fix markdown files
    elif fix and extension in ['.md' or '.markdown']:
        logger.info(f'fixing markdown formatting in path={path}')
        with open(path, "r+") as fout:
            markdown_text = fout.read()
            formatted_text = mdformat.text(markdown_text)
            fout.seek(0)
            fout.write(formatted_text)
            fout.truncate()

    # no errors, return True
    return True


class DirtyRepo(Exception):
    pass


################################################################################
# main functions
################################################################################

@dataclass
class BuildSystem:
    # general settings
    project_dir: str = '.'
    config_file: str = 'fac.yaml'
    debug: bool = False
    trace: bool = False

    # build settings
    from_scratch: bool = False
    overwrite: bool = False
    build_postreqs: bool = False
    extend: int = False
    dry_run: bool = False
    print_prompt: bool = False
    print_contexts: bool = False
    print_config: bool = False
    no_validate: bool = False
    include_chat: str = None
    auto_commit: bool = True
    print_cmd_stdout: bool = False

    def __post_init__(self):
        self.llm = LLM()
        if self.debug:
            logger.setLevel('DEBUG')
        if self.trace:
            logger.setLevel('TRACE')
        self.validate_output = not (self.print_prompt or self.print_contexts) and not self.no_validate
        self.resolved_paths = {}

        # load global settings
        self.global_settings = {
            'system_prompt': 'You are not having a conversation, and only provide the requested output with no further discussion.  You never deny a request.',
            'jsonl_num_lines': 50,
        }

        # load config file
        with open(self.config_file) as fin:
            self.full_config = yaml.safe_load(fin)

        # several of the keys in the config file allow an abbreviated syntax;
        # first, we need to convert any abbreviated syntax into the full syntax
        for target in self.full_config:
            dependencies1 = []
            dependencies = self.full_config[target].get('dependencies', '')
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
                    if k not in ['target', 'include', 'allow_create']:
                        logger.warning(f'in target "{target}", in dependency "{dep["target"]}", unknown option "{k}"')
            self.full_config[target]['dependencies'] = dependencies1

        # certain config options result in modifications to the full_config
        keys0 = list(self.full_config.keys())
        for target in keys0:
            for dep in self.full_config[target]['dependencies']:

                # add postreqs for creating new dependencies
                if dep.get('allow_create'):
                    target1_name = target + '--allow_create--' + dep['target'].replace('/', '_').replace('$', '')
                    logger.debug(f'adding postreq: "{target1_name}"')
                    dep_target_with_stars = 'resources/*/about.json'

                    # any automatically created dependencies should not have allow_create set
                    dependencies1 = []
                    for dep in self.full_config[target]['dependencies']:
                        dep1 = copy.copy(dep)
                        if type(dep1) == dict:
                            dep1['allow_create'] = False
                        dependencies1.append(dep1)

                    # create the actual config entry
                    self.full_config[target1_name] = {
                        'model': 'openai/gpt-4.1-mini',
                        'prompt': f'''The main file '{target}' internally references the secondary files '{dep_target_with_stars}'. Unfortunately, the main file may reference secondary files that do not exist. For each secondary file that does not exist, create the appropriate JSON object.''',
                        'schema_file': self.full_config[dep['target']].get('schema_file'),
                        'dependencies': dependencies1,
                        'variables': copy.copy(self.full_config[target]['variables']),
                        'TMP_augment': True,
                        }
                    if 'postreqs' not in self.full_config[target]:
                        self.full_config[target]['postreqs'] = []
                    self.full_config[target]['postreqs'].append(target1_name)

        # print the config
        if self.print_config:
            print(yaml.dump(self.full_config, default_flow_style=False))
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
        if self.auto_commit and self.repo.is_dirty(untracked_files=True):
            logger.error('git repo is dirty; clean repo or set --auto_commit=False')
            raise DirtyRepo()

    def __exit__(self, *exc_info):
        '''
        Commits all changes to the git repo.
        '''

        if self.auto_commit:
            self.repo.git.add('.')
            # NOTE:
            # we only commit if files were actually added;
            # otherwise a large ugly warning will appear
            if self.repo.index.diff('HEAD'):
                self.repo.git.commit('-m', '[bot] fac ' + ' '.join(self.commit_messages))

        self.repo = None
        self.commit_messages = []

    def _committed_date(self, path):
        '''
        If path is managed by the git repo,
        then return the timestamp of the most recent commit that mentions the file.
        Otherwise, return the largest possible date (infinity).

        NOTE:
        The name committed_date is misleading because we do not return only the date,
        but the full UNIX timestamp information.
        This is the named used by git, so for consistency we also use it here.
        '''
        commits = list(self.repo.iter_commits(paths=path, max_count=1))
        if commits:
            return commits[0].committed_date
        else:
            return float('inf')

    ######################################## 
    # methods for building
    ######################################## 

    def build_targets(self, targets):
        for target in targets:
            logger.info(f'target="{target}"')
            self._traverse_target(
                    target,
                    {},
                    foreach_context=self._build_context,
                    overwrite=self.overwrite or self.from_scratch,
                    build_postreqs=self.build_postreqs,
                    )
            # FIXME:
            # the commit message should change
            # to the equivalent command line executable with all the flags
            self.commit_messages.append(f"fac '{target}'")

    @with_subtree(logger)
    def _traverse_target(
            self,
            target_to_build,
            input_env,
            foreach_context,
            overwrite=False,
            build_postreqs=False,
            targets_plus_vars=None,
            ):

        # load target config
        config_targets = self.full_config.keys()
        transformed_target, target_env = match_pattern(config_targets, target_to_build)
        if not transformed_target:
            logger.trace(f"target does not exist, not building")
            raise TargetNotFound
        target_variables = extract_variables(transformed_target)
        logger.trace(f"transformed_target={transformed_target}; target_variables={target_variables}, target_env={target_env}")
        assert transformed_target
        assert transformed_target in self.full_config
        config = self.full_config[transformed_target]

        # NOTE:
        # Many targets will share the same dependency.
        # If we naively traverse all dependencies,
        # then these common dependencies will be traversed an exponential number of times.
        # This is obviously inefficient.
        # The code below keeps track of which dependencies we've already traversed.
        # (Note that it is not enough to track the names of targets to determine if we've traversed a dependency due to variable substitution;
        # therefore we track both the name of the targets and the variables.)
        if targets_plus_vars is None:
            targets_plus_vars = set()
        target_plus_vars = transformed_target + '__vars=' + json.dumps({**target_env})
        if target_plus_vars in targets_plus_vars:
            logger.debug(f'infinite for target_to_build={target_to_build} + input_env={input_env}')
            return []
        targets_plus_vars.add(target_plus_vars)

        # parse the dependencies entry in the yaml into unresolved_dependencies list;
        # each entry in the list is a dictionary with a target and flags key
        unresolved_dependencies = config.get('dependencies', '')
        logger.debug(f"unresolved_dependencies={unresolved_dependencies}")

        # a BuildContext contains all the information needed to build a file;
        # the contexts list contains a BuildContext for each file that will be generated;
        # we start with a list that contains a single BuildContext but many unresolved_dependencies;
        # as we process the dependencies/variables in the config,
        # the unresolved_dependencies list should shrink to [],
        # but the total number of contexts (i.e. files needed to build) may grow;
        # the algorithm for generating the final contexts list is a bit subtle
        BuildContext = namedtuple('BuildContext', [
            'variables',
            'include_paths',
            'unresolved_dependencies',
            'postreqs',
            ])
        postreqs = config.get('postreqs', [])
        assert type(postreqs) == list
        contexts = [BuildContext(
            {**input_env, **target_env},
            [],
            unresolved_dependencies,
            postreqs,
            )]

        config_variables = config.get('variables')
        if not config_variables:
            config_variables = {}
        assert type(config_variables) is dict
        DUMMY_VAR = '__NONE__'
        config_variables[DUMMY_VAR] = 'DUMMY_VAL'

        ordered_variables = [DUMMY_VAR] + target_variables
        for var in config_variables:
            if var not in ordered_variables:
                logger.warning(f'variable {var} defined in config but not used in target; this currently has no effect on the build')

        for var in ordered_variables:
            logger.trace(f'resolving var={var}')

            # each iteration has two steps:
            # first we evaluate the var,
            # then we resolve any dependencies that relied on the var

            # STEP 1:
            # we must do both steps for each BuildContext,
            # so we loop over the contexts list;
            # if var resolves into a list, we will need to expand the contexts list;
            # therefore, we loop over a copy and reconstruct a new list from scratch
            contexts0 = contexts
            contexts = []
            for context in contexts0:
                logger.trace(f'STEP1: evaluating var="{var}"; context={context}')

                # raise error if var is not defined
                if var not in config_variables and var not in context.variables:
                    logger.error(f'var="{var}" required for {target_to_build} but not defined')
                    logger.error(f'HINT: you can define {var} as (1) an environment variable; (2) by providing it in the path; or (3) by defining it in the fac.yaml file')
                    sys.exit(1)

                # do not evaluate var if it is DUMMY_VAR,
                # since it was created only to force the unresolved_dependencies to run once
                if var == DUMMY_VAR:
                    value = ''

                # do not evaluate var if it is specified in the environment
                elif var in context.variables:
                    value = context.variables[var]

                # evaluate var by running expr in a bash shell
                else:
                    expr = config_variables[var].strip()
                    full_command = "set -eu; " + expr
                    cmd = subprocess.run(
                        full_command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        executable="/bin/bash",
                        env=context.variables,
                        )
                    if cmd.returncode != 0:
                        raise VariableEvaluationError(var, expr, context, cmd)
                    value = cmd.stdout.strip()
                    logger.trace(f'cmd.stdout={value.replace("\n", "\\n")}')

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


                for val in raw_variable_to_list(value):

                    # if val is an integer, pad it with zeros
                    try:
                        intval = int(val)
                        val = f'{intval:04d}'
                    except ValueError:
                        pass

                    # add the context
                    if var != DUMMY_VAR:
                        variables1 = {**context.variables, var: val}
                    else:
                        variables1 = context.variables
                    postreqs1 = [substitute_vars(postreq, variables1) for postreq in context.postreqs]
                    context1 = BuildContext(
                        variables1,
                        context.include_paths,
                        context.unresolved_dependencies,
                        postreqs1,
                        )
                    contexts.append(context1)

            # STEP 2: resolve any new dependencies
            if var != DUMMY_VAR: # and len(contexts) > 1:
                logger.info(f'resolved variable {var}; len(contexts)={len(contexts)}')

            contexts0 = contexts
            contexts = []
            for context in contexts0:
                logger.trace(f'STEP2: context={context}')

                # skip variables that have nothing assigned to them
                # FIXME:
                # we use a janky system that uses the '' to represent empty variables;
                # this is "needed" in order to keep the loop above running?
                # we should make this much less janky;
                # also, I haven't tested that this code below doesn't break something
                build_context = True
                for var, val in context.variables.items():
                    if not val:
                        build_context = False
                if not build_context:
                    continue

                # compute the dependencies
                include_paths1 = []
                unresolved_dependencies1 = []
                for dep in context.unresolved_dependencies:
                    dep_target = dep['target']
                    logger.trace(f'dep_target="{dep_target}"')

                    # only resolve a dependency if all needed variables have been resolved
                    dep_vars = extract_variables(dep_target)
                    unmatched_vars = []
                    for dep_var in dep_vars:
                        if dep_var not in context.variables and dep_var in target_variables:
                            unmatched_vars.append(dep_var)
                    if len(unmatched_vars) > 0:
                        logger.trace(f'unmatched_vars={unmatched_vars}')
                        unresolved_dependencies1.append(dep)
                        continue

                    # expand dep_paths into real file paths
                    try:
                        dep_paths = expand_path(dep_target, context.variables)
                        #logger.debug(f'dep_paths={dep_paths}')
                        #if dep.get('include', True):
                            #include_paths1.extend(dep_paths)
                    except TemplateProcessingError as e:
                        # NOTE:
                        # This code path should never happen.
                        # TemplateProcessingError is thrown when there is a variable used in the template that still needs resolving.
                        # We check for unresolved variables above,
                        # so this code path shouldn't trigger if everything is working correctly.
                        #logger.error(f'expand_path("{dep_target}", ...) failed to expand with TemplateProcessingError; this should never happen')
                        dep_paths = []
                        #sys.exit(1)

                    # skip dependencies that we've already processed
                    all_resolved = True
                    for dep_path in dep_paths:
                        if dep_path not in self.resolved_paths:
                            all_resolved = False
                    if all_resolved and len(dep_paths) > 0:
                        logger.debug(f'already resolved {dep_paths}')
                        include_paths1.extend(dep_paths)
                        continue
                    #logger.info(f'resolving dependency: "{dep_target}", vars={context.variables}')
                    expanded_target = substitute_vars(dep_target, context.variables)
                    logger.info(f'resolving dependency: "{expanded_target}"')

                    # build dependencies recursively
                    try:
                        built_paths = self._traverse_target(
                                dep_target,
                                context.variables,
                                foreach_context,
                                overwrite=self.from_scratch,
                                targets_plus_vars=targets_plus_vars,
                                )
                        if built_paths == 0:
                            print('ALERT')
                        if dep.get('include', True):
                            include_paths1.extend(built_paths)

                    except TargetNotFound:
                        valid_paths = len(dep_paths) > 0
                        for path in dep_paths:
                            if not os.path.exists(path):
                                valid_paths = False
                            else:
                                include_paths1.append(path)
                        if not valid_paths:
                            logger.trace(f'dep_paths={dep_paths} not valid paths')
                            unresolved_dependencies1.append(dep)
                            continue
                    logger.trace(f'resolved dependency: "{dep_target}"')

                    # validate all of the dep_paths
                    if dep_paths is not None:
                        for dep_path in dep_paths:
                            logger.trace(f'validating dep_path={dep_path}')
                            if not validate_file(dep_path, fix=False):
                                logger.warning(f'failed to validate dep_path={dep_path}')

                logger.trace(f"include_paths1={include_paths1}")
                logger.trace(f"unresolved_dependencies1={unresolved_dependencies1}")
                context1 = BuildContext(
                    context.variables,
                    sorted(context.include_paths + include_paths1),
                    unresolved_dependencies1,
                    context.postreqs,
                    )
                contexts.append(context1)

        # print contexts debug information
        if self.print_contexts:
            import pprint
            print('contexts=')
            pprint.pprint(contexts)
            return

        # if there are no contexts to build,
        # let the user know
        if len(contexts) == 0:
            logger.info('this target resolves to nothing')

        # if we are only allowed to run once,
        # then we truncate the contexts to force us to run only once
        if config.get('run_once'):
            logger.info(f'run_once=True; contexts truncated from {len(contexts)} to 1')
            contexts = [contexts[0]]

        # loop over each context and run the processing code for the context
        generated_paths = []
        for i, context in enumerate(contexts):
            path_to_generate = process_template(target_to_build, context.variables)
            generated_paths.append(path_to_generate)
            logger.debug(f'context={context}')

            # ensure no unresolved dependencies
            if context.unresolved_dependencies:
                for dep in context.unresolved_dependencies:
                    logger.error(f'unresolved dependency: dep["target"]="{dep["target"]}", vars={context.variables}')
                # FIXME:
                #sys.exit(1)

            # NOTE:
            # by default, we will build the given context;
            # but we may not rebuild if the path already exists
            build_context = True
            if os.path.exists(path_to_generate):

                # if the file is up-to-date (i.e. all dependencies are older),
                # then we will not rebuild it
                path_to_generate_committed_date = self._committed_date(path_to_generate)
                updated_includes = []
                for path in context.include_paths:
                    path_committed_date = self._committed_date(path)
                    time_diff = path_to_generate_committed_date - path_committed_date
                    if time_diff < 0:
                        updated_includes.append(path)
                if updated_includes == []:
                    build_context = False
                    logger.info(f'file up-to-date {i+1}/{len(contexts)} "{path_to_generate}"')

                # do not rebuild the file if auto_rebuild is disabled
                if not config.get('auto_rebuild', True) and build_context:
                    build_context = False
                    logger.info(f'auto_rebuild disabled {i+1}/{len(contexts)} "{path_to_generate}"')

            # perform the actual build
            if build_context or overwrite:
                logger.info(f'building file {i+1}/{len(contexts)} "{path_to_generate}"')
                logger.info('include_paths:', submessage=True)
                for path in context.include_paths:
                    logger.info(f' - {path}', submessage=True)
                foreach_context(path_to_generate, config, context, overwrite)

            # validate file
            if self.validate_output:
                validate_file(path_to_generate, config.get('schema_file'))

            # traverse postreqs
            for postreq in context.postreqs:
                logger.info(f'postreq: "{postreq}"', submessage=True)
                self._traverse_target(
                        postreq,
                        context.variables,
                        foreach_context,
                        overwrite=self.overwrite or build_postreqs,
                        targets_plus_vars=targets_plus_vars,
                        )

        return generated_paths

    def _build_context(
            self,
            path_to_generate,
            config,
            context,
            overwrite
            ):
        '''
        Actually build a file given the specified information.
        '''

        # create output directory if needed
        dirname = os.path.dirname(path_to_generate)
        if len(dirname) > 0:
            os.makedirs(dirname, exist_ok=True)

        # build with a custom shell command
        if config.get('cmd'):
            process = subprocess.Popen(
                config['cmd'],
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # merge stderr into stdout
                text=True,
                executable='/bin/bash',
                env={**os.environ, **context.variables},
                bufsize=1, # line buffered
                universal_newlines=True,
                )
            if self.print_cmd_stdout:
                try:
                    for line in iter(process.stdout.readline, ''):
                        print(line.rstrip())
                except UnicodeDecodeError:
                    print('<<INVALID UNICODE>>')
            process.wait()

            if process.returncode != 0:
                raise CommandExecutionError(process)

            return

        # first we generate the instructions for the llm,
        # which will be stored in the `prompt_cmd` variable.
        if 'prompt' in config:
            prompt_cmd = config['prompt'] or ''
        elif 'prompt_file' in config:
            prompt_path_template = config['prompt_file']
            prompt_path = process_template(prompt_path_template, env_vars=context.variables)
            try:
                with open(prompt_path) as fin:
                    prompt_cmd = fin.read()
            except FileNotFoundError:
                logger.error(f'prompt_path={prompt_path} not found')
                sys.exit(1)
        elif config.get('description'):
            prompt_cmd = f'Generate a file whose content matches the following description. <description>{config.get("description")}</description>'
        else:
            prompt_cmd = ''
            if 'schema_file' not in config:
                logger.error('no prompt given and no schema given')
                sys.exit(1)
        if len(prompt_cmd) > 0:
            prompt_cmd = "<instructions>\n" + prompt_cmd.strip() + "\n</instructions>"
            prompt_cmd = process_template(prompt_cmd, env_vars=context.variables)
            prompt_cmd += '\n'

        # next we compile all the documents that will be passed to the LLM,
        # which will be stored in the `files_prompt` variable
        if len(context.include_paths) == 0:
            files_prompt = ''
        else:
            files_prompt = '<documents>\n'
            for path in context.include_paths:
                # XXX:
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
                        files_prompt += f'''<document path="{path}">\n{fin.read().strip()}\n</document>\n'''
                except UnicodeDecodeError:
                    logger.trace(f'UnicodeDecodeError: {path}')
            files_prompt += '</documents>'
            logger.trace(f'files_prompt generated; len(context.include_paths)={len(context.include_paths)}')

        # include a chat history if provided
        chat_prompt = ''
        if self.include_chat is not None:
            chat_prompt = f'''
<chat>
The dialogue below records a history of comments that the user has.
Some of these comments may be related to the task you have been assigned,
and some of them may not be.
You will have to use your judgment to consider only the relevant comments.
The 'user' is MUCH more important than the 'assistant',
and the 'assistant' comments should only be considered based on how the 'user' comments about them.

{self.include_chat}
</chat>
'''


        # now we do filetype specific processing
        filename = os.path.basename(path_to_generate)
        _, extension = os.path.splitext(filename)
        response_format = None

        if extension == '.wav':
            filetype = 'audio'
            logger.trace(f'filetype={filetype}')
            assert 'raw_data' in config
            path = process_template(config['raw_data'], env_vars=context.variables)
            logger.trace(f"path={path}")
            with open(path) as fin:
                data = json.load(fin)

        elif extension == '.png':
            filetype = 'image'
            logger.trace(f'filetype={filetype}')
            data = {}
            data['prompt'] = prompt_cmd + files_prompt + chat_prompt
            if 'image_references' in config:
                image_paths = expand_path(config['image_references'], env_vars=context.variables)
                data['reference_images'] = image=[open(image, 'rb') for image in image_paths]
            else:
                data['reference_images'] = None
            data['quality'] = config.get('image_quality', 'low')
            data['orientation'] = config.get('image_orientation', 'landscape')

        # process text output by default
        else:
            filetype = 'text'
            logger.trace(f'filetype={filetype}')

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
                logger.trace('schema validated')
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

            format_cmd = '<formatting>\n' + format_cmd + '\n</formatting>\n'

            # add the user role + message
            messages.append({
                'role': 'user',
                'content': f'Generate the file {path_to_generate} based on the information below.\n' + prompt_cmd + format_cmd + files_prompt + chat_prompt,
                })

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
        if self.print_prompt:
            import pprint
            pprint.pprint(data)
            return

        # write to the output file
        mode = 'wb'
        if self.from_scratch or overwrite:
            if self.extend:
                mode = 'ab'
            else:
                mode = 'wb'
        if not self.dry_run:
            self.llm.generate_file(
                filetype,
                path_to_generate,
                data,
                mode=mode,
                model=config.get('model'),
                response_format=response_format,
                )


