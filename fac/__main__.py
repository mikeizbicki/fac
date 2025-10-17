#!/usr/bin/env python3
'''
`fac` is a build system for LLM-based agentic projects.
The Latin verb `facio` means to do/make, and fac is the imperative form.
'''

# standard lib imports
from collections import namedtuple, Counter
from dataclasses import dataclass, fields
import base64
import copy
import datetime
import glob
import itertools
import json
import os
import math
import pathlib
import re
import string
import subprocess
import sys
import tempfile
import typing

# external lib imports
import jsonschema
import mdformat
import yaml

# project imports
from .Logging import logger, with_subtree
from .LLM import LLM

################################################################################
# helper functions
################################################################################


def substitute_vars(template_str, vars_dict=None):
    r"""
    Substitute variables in a string with values from a dictionary.

    If a variable is not found in the dictionary, it remains unchanged.

    >>> substitute_vars('Path is $VAR1 and $VAR2', {'VAR1': 'value1'})
    'Path is value1 and $VAR2'
    >>> substitute_vars('Path is $VAR1 and $VAR2', {'VAR2': 'value2'})
    'Path is $VAR1 and value2'
    >>> substitute_vars('Path is $VAR1 and $VAR2', {'VAR1': 'value1', 'VAR2': 'value2'})
    'Path is value1 and value2'
    >>> substitute_vars('Path is ${VAR1} and ${VAR2}', {'VAR1': 'value1', 'VAR2': 'value2'})
    'Path is value1 and value2'
    >>> substitute_vars('Path is $VAR1 and ${VAR2}', {'VAR1': 'value1', 'VAR2': 'value2'})
    'Path is value1 and value2'
    >>> substitute_vars('Path is ${VAR1} and $VAR2', {'VAR1': 'value1', 'VAR2': 'value2'})
    'Path is value1 and value2'
    >>> substitute_vars('Path is $VAR1 and $VAR2', {})
    'Path is $VAR1 and $VAR2'

    :param template_str: The input string with variables.
    :param vars_dict: A dictionary with variable names as keys and their values.
    :return: The string with variables substituted.
    """
    for var, value in vars_dict.items():
        template_str = template_str.replace(f'${var}', value)
        template_str = template_str.replace(f'${{{var}}}', value)
    return template_str


def process_template(template_content, env_vars=None):
    """
    Process a template string by evaluating shell expressions within it.

    This function takes a template string, creates a temporary shell script that
    processes the template using shell expansions (like $(...) and $variables),
    and returns the resulting output.

    Args:
        template_content (str): The template string with shell expressions
        env_vars (dict, optional): Dictionary of environment variables to set

    Returns:
        str: The processed template with all shell expansions evaluated

    Examples:
        >>> # Simple variable substitution
        >>> process_template("Hello $NAME!", {'NAME': 'World'})
        'Hello World!'

        >>> # Command substitution
        >>> process_template("Today is $(echo Monday).")
        'Today is Monday.'

        >>> # Math operations in shell
        >>> process_template("2 + 3 = $(expr 2 + 3)")
        '2 + 3 = 5'

        >>> # Conditional expressions
        >>> template = '''$(
        ... if [ 1 -eq 1 ]; then
        ...   echo "True"
        ... else
        ...   echo "False"
        ... fi
        ... )'''
        >>> process_template(template)
        'True'

        >>> # Error in shell code: unmatched paren
        >>> process_template("2 + 3 = $(expr 2 + 3")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        TemplateProcessingError: ...

        >>> # Error in shell code: using a var that doesn't exist
        >>> process_template("blah blah $_UNDEFINED_VAR")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        TemplateProcessingError: ...

        >>> # WARNING:
        >>> # internally, this function uses the shell's heredoc feature;
        >>> # errors from within subshells are not propagated within heredocs;
        >>> # so by default the following command would not generate an error;
        >>> # but we want it to generate an error, so we capture stderr,
        >>> # and throw an error whenever stderr is non-empty;
        >>> # this gets the correct behavior for the following command
        >>> process_template("blah blah $(echo $_UNDEFINED_VAR)")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        TemplateProcessingError: blah
        >>> # the downside of this approach is that
        >>> # non-erroring commands that write to stderr will generate template errors
        >>> process_template("blah blah $(echo blah >&2)")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ...
        TemplateProcessingError: blah
    """
    if env_vars is None:
        env_vars = {}

    # Create a temporary shell script
    fd, script_path = tempfile.mkstemp(suffix='.sh')
    try:
        # Close the file descriptor returned by mkstemp
        os.close(fd)

        # Write to the file using a regular file handle
        with open(script_path, 'w') as script:
            # Write a shell script that will output the processed template
            script.write('#!/bin/bash\n')
            script.write('set -e\n')  # Exit immediately if a command exits with non-zero status
            script.write('set -u\n')  # Treat unset variables as an error

            # Use cat with a heredoc to process the template
            script.write('cat << __EOF_DELIMITER_END\n')
            script.write(template_content)
            script.write('\n__EOF_DELIMITER_END\n')

        # Make the script executable
        os.chmod(script_path, 0o755)

        # Execute the script and capture output
        result = subprocess.run([script_path], capture_output=True, text=True, env={**os.environ, **env_vars})
        if result.returncode != 0 or len(result.stderr.strip()) > 0:
            raise TemplateProcessingError(result.returncode, result.stdout, result.stderr)
        return result.stdout.strip()

    finally:
        # Ensure the temporary file is removed
        if os.path.exists(script_path):
            os.unlink(script_path)


class TemplateProcessingError(Exception):
    """Exception raised when template processing fails."""

    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(stderr)


class CommandExecutionError(Exception):
    def __init__(self, result):
        self.result = result
        super().__init__(result.stderr)


class VariableEvaluationError(Exception):
    def __init__(self, var, expr, context, result):
        errorstrs = [
            f'error evaluating {var}=$({expr})',
            f'context={context}',
            f"result.returncode={result.returncode}",
            f"result.stdout={result.stdout}",
            f"result.stderr={result.stderr}",
            ]
        super().__init__('\n'.join(errorstrs))


class EmptyVariableError(Exception):
    def __init__(self, var, expr):
        errorstrs = [
            f'{var}=$({expr})',
            ]
        super().__init__('\n'.join(errorstrs))


class TargetNotFound(Exception):
    pass


def expand_path(path, env_vars=None):
    """
    Expand environment variables and wildcards in a path.

    Args:
        path (str): The path with potential environment variables and wildcards
        env_vars (dict, optional): Dictionary of environment variables to use

    Returns:
        list: List of expanded paths

    The following example creates a tempdir and places two files inside of it.
    Then the `expand_path` function is used to list those files.
    The output is wrapped in `len` because the output paths are non-deterministic.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmpdir:
    ...     test_env = {'PY_TEST_VAR': tmpdir}
    ...     open(os.path.join(tmpdir, 'test1.txt'), 'w').close()
    ...     open(os.path.join(tmpdir, 'test2.txt'), 'w').close()
    ...     len(expand_path('$PY_TEST_VAR/*.txt', test_env))
    2

    If the input string uses an environment variable that is undefined,
    then a `TemplateProcessingError` will be raised.

    >>> with tempfile.TemporaryDirectory() as tmpdir:
    ...     expand_path('$PY_TEST_VAR2/*.txt', {}) # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    TemplateProcessingError: ...
    """
    # Use process_template to handle environment variable expansion
    expanded_path = process_template(path, env_vars)

    # Handle wildcards with glob
    paths = glob.glob(expanded_path)
    paths = [str(pathlib.Path(path).resolve()) for path in paths]
    paths = [os.path.relpath(path) for path in paths]

    return paths


def extract_variables(pattern):
    """
    Extract variables from a single pattern string.

    Args:
        pattern (str): Pattern string with variables like "$SERIES/$STORY/outline.json"

    Returns:
        list: List of variable names used in the pattern

    Examples:
        >>> extract_variables("$SERIES/$STORY/outline.json")
        ['SERIES', 'STORY']

        >>> extract_variables("$SERIES/$STORY/chapter$CHAPTER/chapter.json")
        ['SERIES', 'STORY', 'CHAPTER']

        >>> extract_variables("$SERIES/characters/$CHARACTER/about.json")
        ['SERIES', 'CHARACTER']

        >>> extract_variables("test_project/outline.json")
        []
    """
    variables = re.findall(r'\$(\w+)', pattern)
    return variables


def match_pattern(patterns, input_string):
    """
    Match an input string against a list of patterns and extract variables.

    Args:
        patterns: List of pattern strings with variables like "$SERIES/$STORY/outline.json"
        input_string: String to match against patterns, e.g. "a/b/outline.json"
                     If input_string contains variables like $STORY, no extraction is done for those

    Returns:
        Tuple of (matched_pattern, extracted_variables) or (None, {}) if no match

    Raises:
        TemplateProcessingError: If multiple patterns match the input string (ambiguous patterns)

    Examples:

        >>> patterns = ["$SERIES/$STORY/outline.json"]
        >>> match_pattern(patterns, "a/b/outline.json")
        ('$SERIES/$STORY/outline.json', {'SERIES': 'a', 'STORY': 'b'})

        >>> patterns = ["$SERIES/$STORY/chapter$CHAPTER/chapter.json"]
        >>> match_pattern(patterns, "mystory/adventure/chapter3/chapter.json")
        ('$SERIES/$STORY/chapter$CHAPTER/chapter.json', {'SERIES': 'mystory', 'STORY': 'adventure', 'CHAPTER': '3'})

        >>> patterns = ["$SERIES/characters/$CHARACTER/about.json"]
        >>> match_pattern(patterns, "starwars/characters/luke/about.json")
        ('$SERIES/characters/$CHARACTER/about.json', {'SERIES': 'starwars', 'CHARACTER': 'luke'})

        >>> patterns = ["$SERIES/$STORY/outline.json", "$SERIES/$STORY/locations.json"]
        >>> match_pattern(patterns, "a/b/locations.json")
        ('$SERIES/$STORY/locations.json', {'SERIES': 'a', 'STORY': 'b'})

    If `input_string` does not match any patterns,
    then we return `(None, {})`.

        >>> patterns = ["$SERIES/$STORY/outline.json"]
        >>> match_pattern(patterns, "a/b/c/outline.json")
        (None, {})

        >>> patterns = ["$SERIES/$STORY/outline.json"]
        >>> match_pattern(patterns, "a/b/summary.json")
        (None, {})

    If there are `.` references to the current directory,
    we should still match the pattern.

        >>> patterns = ['$PROJECT/outline.json', '$PROJECT/$LEVEL1/blurb.json']
        >>> match_pattern(patterns, 'test_project/outline.json')
        ('$PROJECT/outline.json', {'PROJECT': 'test_project'})

        >>> patterns = ['./$PROJECT/outline.json', '$PROJECT/$LEVEL1/blurb.json']
        >>> match_pattern(patterns, 'test_project/outline.json')
        ('$PROJECT/outline.json', {'PROJECT': 'test_project'})

        >>> patterns = ['././$PROJECT/./outline.json', '$PROJECT/$LEVEL1/blurb.json']
        >>> match_pattern(patterns, 'test_project/outline.json')
        ('$PROJECT/outline.json', {'PROJECT': 'test_project'})

        >>> patterns = ['./$PROJECT/outline.json', '$PROJECT/$LEVEL1/blurb.json']
        >>> match_pattern(patterns, './test_project/outline.json')
        ('$PROJECT/outline.json', {'PROJECT': 'test_project'})

        >>> patterns = ['./$PROJECT/./outline.json', '$PROJECT/$LEVEL1/blurb.json']
        >>> match_pattern(patterns, './test_project/outline.json')
        ('$PROJECT/outline.json', {'PROJECT': 'test_project'})

        >>> patterns = ['$PROJECT/./outline.json', '$PROJECT/$LEVEL1/blurb.json']
        >>> match_pattern(patterns, './test_project/outline.json')
        ('$PROJECT/outline.json', {'PROJECT': 'test_project'})

    If there are multiple patterns that could match,
    then the choice of pattern is ambiguous.
    Raise a ValueError.
    This likely indicates a problem with the structure of the dependencies in the config.

        >>> patterns = ["$A/$B/$C/file.json", "$X/something/$Y/file.json"]
        >>> match_pattern(patterns, "first/something/second/file.json")
        Traceback (most recent call last):
            ...
        ValueError: Ambiguous pattern match for 'first/something/second/file.json'

    If we pass a variable in the `input_string`,
    we should not match that variable to one of the patterns in the returned variable list.

        >>> patterns = ["$SERIES/$STORY/outline.json"]
        >>> match_pattern(patterns, "a/$STORY/outline.json")
        ('$SERIES/$STORY/outline.json', {'SERIES': 'a'})

        >>> patterns = ["$SERIES/$STORY/chapter$CHAPTER/chapter.json"]
        >>> match_pattern(patterns, "a/b/chapter$CHAPTER/chapter.json")
        ('$SERIES/$STORY/chapter$CHAPTER/chapter.json', {'SERIES': 'a', 'STORY': 'b'})

        >>> patterns = ["$SERIES/$STORY/chapter$CHAPTER/chapter.json"]
        >>> match_pattern(patterns, "$SERIES/$STORY/chapter$CHAPTER/chapter.json")
        ('$SERIES/$STORY/chapter$CHAPTER/chapter.json', {})

        >>> patterns = ["$SERIES/$STORY/chapter$CHAPTER/chapter.json"]
        >>> match_pattern(patterns, "$SERIES/b/chapter$CHAPTER/chapter.json")
        ('$SERIES/$STORY/chapter$CHAPTER/chapter.json', {'STORY': 'b'})
    """
    import re
    import os

    # Normalize input string by removing './' references
    norm_input = re.sub(r'(\.\/)+', '', input_string)

    # Create a mapping of normalized patterns to original patterns
    norm_to_orig = {}
    normalized_patterns = []

    for pattern in patterns:
        # Normalize pattern by removing './' references
        norm_pattern = re.sub(r'(\.\/)+', '', pattern)
        normalized_patterns.append(norm_pattern)
        norm_to_orig[norm_pattern] = pattern

    matched_patterns = []
    matched_vars = []

    input_segments = norm_input.split('/')

    for norm_pattern in normalized_patterns:
        pattern_segments = norm_pattern.split('/')

        # Skip patterns with different number of segments
        if len(pattern_segments) != len(input_segments):
            continue

        variables = {}
        is_match = True

        for i, (p_seg, i_seg) in enumerate(zip(pattern_segments, input_segments)):
            # Check if pattern segment contains variables
            if '$' in p_seg:
                # Convert pattern segment to regex
                regex = '^'
                pos = 0
                var_names = []

                while pos < len(p_seg):
                    if p_seg[pos] == '$':
                        # Found start of a variable
                        var_start = pos + 1
                        var_end = var_start
                        while var_end < len(p_seg) and (p_seg[var_end].isalnum() or p_seg[var_end] == '_'):
                            var_end += 1

                        var_name = p_seg[var_start:var_end]
                        var_placeholder = f"${var_name}"

                        # Check if this variable appears in input segment
                        if var_placeholder in i_seg:
                            # Match literally
                            regex += re.escape(var_placeholder)
                        else:
                            # Capture the variable value
                            var_names.append(var_name)
                            regex += '(.*?)'

                        pos = var_end
                    else:
                        # Add regular character to regex
                        if p_seg[pos] in '.^$*+?{}[]\\|()':
                            regex += '\\'
                        regex += p_seg[pos]
                        pos += 1

                regex += '$'

                # Apply regex to input segment
                match = re.match(regex, i_seg)

                if not match:
                    is_match = False
                    break

                # Extract captured variables
                for j, var_name in enumerate(var_names):
                    variables[var_name] = match.group(j+1)

            elif p_seg != i_seg:
                # Literal segments must match exactly
                is_match = False
                break

        if is_match:
            matched_patterns.append(norm_pattern)
            matched_vars.append(variables)

    if len(matched_patterns) > 1:
        raise ValueError(f"Ambiguous pattern match for '{input_string}'")

    if matched_patterns:
        # For tests, we should return the clean version of the pattern
        return (matched_patterns[0], matched_vars[0])
    else:
        return (None, {})


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

################################################################################
# main functions
################################################################################

@dataclass
class BuildSystem:
    targets: [str]
    project_dir: str = '.'
    prompt_dir: str = 'prompts'
    config_file: str = 'fac.yaml'
    forward_dependencies: typing.Literal['rebuild', 'touch', 'none'] = 'rebuild'
    from_scratch: bool = False
    overwrite: bool = False
    build_postreqs: bool = False
    extend: int = False
    dry_run: bool = False
    print_prompt: bool = False
    print_contexts: bool = False
    print_config: bool = False
    no_validate: bool = False
    debug: bool = False
    trace: bool = False

    def __post_init__(self):
        self.llm = LLM()
        if self.debug:
            logger.setLevel(logging.DEBUG)
        if self.trace:
            logger.setLevel(TRACE_LEVEL)
        self.validate_output = not (self.print_prompt or self.print_contexts) and not self.no_validate
        self.resolved_paths = {}
        self.targets_plus_vars = set()

        # load global settings
        self.global_settings = {
            'system_prompt': 'You are not having a conversation, and only provide the requested output with no further discussion.  You never deny a request.',
            'jsonl_num_lines': 20,
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

        # build all targets
        for target in self.targets:
            logger.info(f'target="{target}"')
            self.build_target(
                    target,
                    {},
                    overwrite=self.overwrite or self.from_scratch,
                    build_postreqs=self.build_postreqs,
                    )

    @with_subtree(logger)
    def build_target(self, target_to_build, input_env, overwrite=False, build_postreqs=False):

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

        # prevent infinite loops # FIXME
        target_plus_vars = transformed_target + '__vars=' + json.dumps({**input_env, **target_env})
        if target_plus_vars in self.targets_plus_vars:
            logger.debug(f'prevented infinite recursion for target_to_build={target_to_build} + input_env={input_env}')
            return [] # FIXME
        self.targets_plus_vars.add(target_plus_vars)


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
                        built_paths = self.build_target(dep_target, context.variables, overwrite=self.from_scratch)
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

                    # update resolved_paths with timestamp information
                    for dep_path in dep_paths:
                        self.resolved_paths[dep_path] = {
                            'mtime': os.path.getmtime(dep_path)
                            }

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
                path_to_generate_mtime = os.path.getmtime(path_to_generate)
                updated_includes = []
                for path in context.include_paths:
                    time_diff = path_to_generate_mtime - self.resolved_paths[path]['mtime']
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
                    for line in iter(process.stdout.readline, ''):
                        print(line.rstrip())
                    process.wait()

                    if process.returncode != 0:
                        raise CommandExecutionError(process)

                # build the target with the LLM
                else:
                    filename = os.path.basename(path_to_generate)
                    self.context_to_file(path_to_generate, config, context, overwrite)

            # validate file
            if self.validate_output:
                validate_file(path_to_generate, config.get('schema_file'))

            # build postreqs
            for postreq in context.postreqs:
                logger.info(f'postreq: "{postreq}"', submessage=True)
                self.build_target(
                        postreq,
                        context.variables,
                        overwrite=self.overwrite or build_postreqs,
                        )

        for path in generated_paths:
            try:
                mtime = os.path.getmtime(path)
            except FileNotFoundError:
                mtime = math.inf
            self.resolved_paths[path] = {
                'mtime': mtime
                }
        return generated_paths

    def context_to_file(self, path_to_generate, config, context, overwrite):

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
                with open(path) as fin:
                    files_prompt += f'''<document path="{path}">\n{fin.read().strip()}\n</document>\n'''
            files_prompt += '</documents>'
            logger.trace(f'files_prompt generated; len(context.include_paths)={len(context.include_paths)}')

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
            data['prompt'] = prompt_cmd + files_prompt
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
            if 'md' or 'markdown' not in extension:
                format_cmd += 'Do not output markdown, and do not put the output inside a codeblock.'
            if extension == '.json':
                format_cmd += 'Output JSON.'
                response_format = {'type': 'json_object'}
            elif extension == '.jsonl':
                response_format = {'type': 'json_object'}
                format_cmd += f'Output JSONL.  Each line of the output should be a single JSON object. There should be at most {self.global_settings["jsonl_num_lines"]} total lines.'
                format_cmd = process_template(format_cmd, env_vars=context.variables)

            if config.get('schema_file'):
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
                'content': prompt_cmd + format_cmd + files_prompt,
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


################################################################################
# CLI
################################################################################

def main():

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('targets', nargs='*')

    # add all other fields from the dataclass as optional arguments
    for field in fields(BuildSystem):
        if field.name != 'targets':
            name = f'--{field.name}'
            if typing.get_origin(field.type) is typing.Literal:
                choices = typing.get_args(field.type)
                parser.add_argument(name, choices=choices, default=field.default)
            elif field.type == bool and field.default == False:
                parser.add_argument(name, action='store_true')
            else:
                parser.add_argument(name, default=field.default)

    args = parser.parse_args()
    build_system = BuildSystem(**vars(args))

if __name__ == '__main__':
    main()
