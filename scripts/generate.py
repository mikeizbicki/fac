#!/usr/bin/env python3

# setup logging
import logging
handler = 'standard'

if handler == 'rich':
    from rich.logging import RichHandler
    handler = RichHandler(
        show_time=False,
        show_path=False,
        keywords=[]
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(message)s',
        '%Y-%m-%d %H:%M:%S'
    ))
else:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        '%Y-%m-%d %H:%M:%S'
    ))
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.propagate = False

# imports
from collections import namedtuple, Counter
import copy
import glob
import json
import os
import pathlib
import string
import subprocess
import sys
import tempfile

import clize
import groq
import openai

################################################################################
# helper functions
################################################################################

class LLM():

    providers = {
        'anthropic': {
            'base_url': 'https://api.anthropic.com/v1/',
            'apikey': 'ANTHROPIC_API_KEY'
            },
        'groq': {
            'base_url': 'https://api.groq.com/openai/v1',
            'apikey': 'GROQ_API_KEY'
            },
        'openai': {
            'base_url': 'https://api.openai.com/v1',
            'apikey': 'OPENAI_API_KEY'
            },
        }

    models = {
        'anthropic/claude-3-haiku-20240307':    {'in_price': 0.25, 'out_price':  1.25},
        'anthropic/claude-sonnet-4-0':          {'in_price': 3.00, 'out_price': 15.00},
        'groq/llama-3.3-70b-versatile':         {'in_price': 0.00, 'out_price':  0.00},
        'openai/gpt-4.1':                       {'in_price': 2.00, 'out_price':  8.00},
        'openai/gpt-4.1-mini':                  {'in_price': 0.40, 'out_price':  1.60},
        }

    def __init__(self):
        #self.model = 'groq/llama-3.3-70b-versatile'
        #self.model = 'openai/gpt-4.1-mini'
        self.model = 'anthropic/claude-3-haiku-20240307'
        self.usage = Counter()

        # connect to the API
        self.provider = self.model.split('/')[0]
        self.model_name = self.model.split('/')[1]
        self.client = openai.Client(
            api_key = os.environ.get(self.providers[self.provider]['apikey']),
            base_url = self.providers[self.provider]['base_url'],
        )

        # load the system prompt
        with open('prompts/system') as fin:
            self.system_prompt = fin.read().strip()

    def text(self, prompt, *, seed=None):
        logger.debug(f'connecting to LLM; prompt_length={len(self.system_prompt) + len(prompt)}')
        result = self.client.chat.completions.create(
            messages=[
                {
                    'role': 'system',
                    'content': self.system_prompt,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            model=self.model_name,
            seed=seed,
        )

        # update usage info
        usage_counter = Counter({
            'completion_tokens': result.usage.completion_tokens,
            'prompt_tokens': result.usage.prompt_tokens,
            })
        self.usage += usage_counter

        #logger.info('LLM.text: ' + self._usage_to_str(usage_counter))
        logger.info(self._usage_to_str(self.usage))
        return result.choices[0].message.content

    def _usage_to_str(self, usage):
        in_price = usage['prompt_tokens'] * self.models[self.model]['in_price'] / 1000000
        out_price = usage['completion_tokens'] * self.models[self.model]['out_price'] / 1000000
        return f'total_price=${in_price + out_price:0.2f} ({usage["prompt_tokens"]} in-tokens = ${in_price:0.2f}, {usage["completion_tokens"]} out-tokens = ${out_price:0.2f})'


def process_template(template_content, env_vars=None):
    """Process a template string by evaluating shell expressions within it.

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
    # Create a temporary shell script
    fd, script_path = tempfile.mkstemp(suffix='.sh')
    try:
        # Close the file descriptor returned by mkstemp
        os.close(fd)

        # Write to the file using a regular file handle
        with open(script_path, 'w') as script:
            # Write a shell script that will output the processed template
            script.write('#!/bin/sh\n')
            script.write('set -e\n')  # Exit immediately if a command exits with non-zero status
            script.write('set -u\n')  # Treat unset variables as an error

            # Add environment variables
            if env_vars:
                for key, value in env_vars.items():
                    script.write(f'export {key}="{value}"\n')

            # Use cat with a heredoc to process the template
            script.write('cat << __EOF_DELIMITER_END\n')
            script.write(template_content)
            script.write('\n__EOF_DELIMITER_END\n')

        # Make the script executable
        os.chmod(script_path, 0o755)

        # Execute the script and capture output
        result = subprocess.run([script_path], capture_output=True, text=True)
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
        message = f"stderr"
        super().__init__(stderr)


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
    then a `ValueError` will be raised.

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
        ValueError: If multiple patterns match the input string (ambiguous patterns)

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

        >>> patterns = ["$SERIES/$STORY/outline.json"]
        >>> match_pattern(patterns, "a/b/c/outline.json")
        (None, {})

        >>> patterns = ["$SERIES/$STORY/outline.json"]
        >>> match_pattern(patterns, "a/b/summary.json")
        (None, {})

        >>> # Ambiguous patterns test
        >>> patterns = ["$A/$B/$C/file.json", "$X/something/$Y/file.json"]
        >>> match_pattern(patterns, "first/something/second/file.json")
        Traceback (most recent call last):
            ...
        ValueError: Ambiguous pattern match for 'first/something/second/file.json'

        >>> # Input with variable - no extraction for that variable
        >>> patterns = ["$SERIES/$STORY/outline.json"]
        >>> match_pattern(patterns, "a/$STORY/outline.json")
        ('$SERIES/$STORY/outline.json', {'SERIES': 'a'})
    """
    import re

    matches = []
    match_results = []

    for pattern in patterns:
        # Split both pattern and input into segments
        pattern_segments = pattern.split('/')
        input_segments = input_string.split('/')

        # If segment counts don't match, continue to next pattern
        if len(pattern_segments) != len(input_segments):
            continue

        variables = {}
        match_failed = False

        # Check each segment
        for pattern_seg, input_seg in zip(pattern_segments, input_segments):
            # Check if input segment is a variable (starts with $)
            if input_seg.startswith('$'):
                # Extract variable name from input
                input_var_name = input_seg[1:]

                # Input segment is a variable, check if pattern segment has the same variable
                if pattern_seg == input_seg:
                    # Exact match, continue to next segment
                    continue
                elif not pattern_seg.startswith('$'):
                    # Pattern segment is not a variable, but input is
                    match_failed = True
                    break
                # Otherwise, pattern segment is a variable but not the same as input
                # We'll handle this in the next condition

            # Process pattern segment if it contains variables
            if '$' in pattern_seg:
                # Skip extraction if input segment is a variable
                if input_seg.startswith('$'):
                    # Check if the variable names match
                    pattern_var = pattern_seg[1:] if pattern_seg.startswith('$') else None
                    input_var = input_seg[1:]

                    if pattern_var == input_var:
                        # Same variable, continue to next segment
                        continue
                    elif pattern_seg.startswith('$'):
                        # Different variables, we don't extract but consider it a match
                        continue
                    else:
                        # Pattern has a complex segment with variables but input is a variable
                        match_failed = True
                        break

                # Input is not a variable, do normal extraction
                # Convert pattern segment to regex
                regex_pattern = '^'
                var_positions = []

                i = 0
                while i < len(pattern_seg):
                    if pattern_seg[i] == '$':
                        # Found a variable
                        var_start = i + 1
                        # Find the end of variable name
                        var_end = var_start
                        while var_end < len(pattern_seg) and pattern_seg[var_end].isalnum():
                            var_end += 1

                        var_name = pattern_seg[var_start:var_end]
                        var_positions.append(var_name)

                        # Add a capturing group to the regex
                        regex_pattern += '(.*?)'
                        i = var_end
                    else:
                        # Regular character, escape special regex chars
                        if pattern_seg[i] in '.^$*+?{}[]\\|()':
                            regex_pattern += '\\'
                        regex_pattern += pattern_seg[i]
                        i += 1

                regex_pattern += '$'

                # Match the regex against the input segment
                match = re.match(regex_pattern, input_seg)
                if not match:
                    match_failed = True
                    break

                # Extract variables from the match
                for i, var_name in enumerate(var_positions):
                    variables[var_name] = match.group(i+1)

            elif pattern_seg != input_seg:
                # Literal segments must match exactly
                match_failed = True
                break

        if not match_failed:
            matches.append(pattern)
            match_results.append((pattern, variables))

    # Check for ambiguous matches
    if len(matches) > 1:
        raise ValueError(f"Ambiguous pattern match for '{input_string}'")

    # Return the match if found, otherwise (None, {})
    return match_results[0] if match_results else (None, {})


################################################################################
# main function
################################################################################

def generate_file(
        pattern_to_build='$SERIES/$STORY/outline.json',
        *,
        prompt_dir='prompts',
        config_path='prompts/config.yaml',
        overwrite=False,
        print_prompt=False,
        print_environments=False,
        environment0=None,
        ):

    if not environment0:
        environment0 = {}

    logger.debug(f'pattern_to_build="{pattern_to_build}"')
    logger.debug(f"environment0={environment0}")
    llm = LLM()

    # load config file
    import yaml
    with open(config_path) as fin:
        full_config = yaml.safe_load(fin)
    config_patterns = full_config.keys()
    transformed_pattern, environment = match_pattern(config_patterns, pattern_to_build)
    logger.debug(f"transformed_pattern={transformed_pattern}; environment={environment}")
    assert transformed_pattern
    assert transformed_pattern in full_config
    config = full_config[transformed_pattern]

    # compute the variables
    environments = [{**environment, **environment0}]
    for var, expr in config.get('variables', {}).items():

        environments0 = environments
        environments = []
        for environment in environments0:

            # the var was specified in the environment,
            # so we do not execute the expr
            if var in os.environ:
                vals  = os.environ[var]

            # run the expr in the bash shell
            else:
                full_command = "set -eu; " + expr
                result = subprocess.run(
                    full_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    executable="/bin/bash",
                    env={**os.environ, **environment},
                    )
                if result.returncode != 0:
                    logger.error(f'evaluating {var}=$({expr} failed)')
                    logger.error(f"result.returncode={result.returncode}")
                    logger.error(f"result.stdout={result.stdout}")
                    logger.error(f"result.stderr={result.stderr}")
                    sys.exit(1)
                vals = result.stdout

            # lists are separated by null characters;
            # for each entry in the list,
            # we will add a new environment with the entry added
            for val in vals.split('\0'):

                # don't add val to the environments list when it is empty;
                # this is because when doing the split on \0,
                # we will always have the last entry be '',
                # because of the tr '\n' '\0' command
                # and all outputs ending in a '\n'
                val = val.strip()
                if val == '':
                    continue

                # if val is an integer, prepend it with zeros
                try:
                    intval = int(val)
                    val = f'{intval:04d}'
                except ValueError:
                    pass

                # add the environment
                environment1 = copy.copy(environment)
                environment1[var] = val
                environments.append(environment1)

    # print environments debug information
    if print_environments:
        import pprint
        pprint.pprint(environments)
        return

    # loop over each environment and run the processing code for the environment
    for i, environment in enumerate(environments):
        logger.debug(f'iteration {i+1}/{len(environments)}; environment={environment}')

        # compute the dependencies
        logger.debug(f'computing dependencies for "{pattern_to_build}"')
        include_paths = []
        deps = config['dependencies'].split()
        for dep_pattern in deps:
            dep_paths = expand_path(dep_pattern, environment)
            if not dep_paths:
                logger.debug(f'no paths found for dep_pattern={dep_pattern}, building')
                generate_file(
                    pattern_to_build=dep_pattern,
                    prompt_dir=prompt_dir,
                    config_path=config_path,
                    overwrite=overwrite,
                    print_prompt=print_prompt,
                    print_environments=print_environments,
                    environment0 = environment,
                    )
            else:
                logger.debug(f'matched: dep_pattern="{dep_pattern}"')
                #logger.debug(f'dependency matched: dep_pattern="{dep_pattern}"; dep_paths={dep_paths}')
            include_paths.extend(dep_paths)
        logger.debug(f"include_paths={include_paths}")

        # after generating dependencies
        logger.info(f'building "{pattern_to_build}"')

        # build with a custom command
        if config.get('cmd'):
            result = subprocess.run(
                config['cmd'],
                shell=True,
                capture_output=True,
                text=True,
                executable="/bin/bash",
                env={**os.environ, **environment},
                )
            if result.returncode != 0:
                logger.error(f"result.returncode={result.returncode}")
                logger.error(f"result.stdout={result.stdout}")
                logger.error(f"result.stderr={result.stderr}")
                sys.exit(1)

        # build the target with the LLM
        else:

            # compute files_prompt
            files_prompt = '<documents>\n'
            for path in include_paths:
                with open(path) as fin:
                    files_prompt += f'''<document path="{path}">
{fin.read().strip()}
</document>
'''
            files_prompt += '</documents>'

            # compute the instructions prompt
            filename = os.path.basename(pattern_to_build)
            _, extension = os.path.splitext(filename)

            if 'prompt_file' in config:
                prompt_path = config['prompt_file']
            else:
                prompt_path = os.path.join(prompt_dir, filename)
            with open(prompt_path) as fin:
                prompt_cmd = fin.read()
                prompt_cmd = process_template(prompt_cmd, env_vars=environment)
                #prompt_cmd = process_template(prompt_cmd, env_vars={**os.environ, **environment})
            
            if extension == '.json':
                format_cmd = '<formatting>JSON with no markdown codeblocks.</formatting>'
            else:
                format_cmd = ''

            # compute full prompt
            prompt = f'''<instructions>
{prompt_cmd}
</instructions>
{format_cmd}
{files_prompt}
'''

            # stop processing if printing the prompt
            if print_prompt:
                print(prompt)
                return

            # write to the output file
            path_to_generate = process_template(pattern_to_build, environment)
            logger.debug(f"path_to_generate={path_to_generate}")
            dirname = os.path.dirname(path_to_generate)
            os.makedirs(dirname, exist_ok=True)
            mode = 'wt' if overwrite else 'xt'
            try:
                with open(path_to_generate, mode) as fout:
                    fout.write(llm.text(prompt))
            except FileExistsError:
                logger.warning(f'file "{path_to_generate}" exists; skipping')

if __name__ == '__main__':
    logger.setLevel(logging.DEBUG)
    #logger.setLevel(logging.INFO)
    clize.run(generate_file)
