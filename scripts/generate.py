#!/usr/bin/env python3

# setup logging
import logging
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    '%Y-%m-%d %H:%M:%S'
))
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

        logger.info('LLM.text: ' + self._usage_to_str(usage_counter))
        logger.info('LLM (running): ' + self._usage_to_str(self.usage))
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
            script.write('#!/bin/bash\n')
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


def expand_path(path):
    """
    Expand environment variables and wildcards in a path.

    The following example creates a tempdir and places two files inside of it.
    Then the `expand_path` function is used to list those files.
    The output is wrapped in `len` because the output paths are non-deterministic.

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmpdir:
    ...     os.environ['PY_TEST_VAR'] = tmpdir
    ...     open(os.path.join(tmpdir, 'test1.txt'), 'w').close()
    ...     open(os.path.join(tmpdir, 'test2.txt'), 'w').close()
    ...     len(expand_path('$PY_TEST_VAR/*.txt'))
    2

    If the input string uses an environment variable that is undefined,
    then a `ValueError` will be raised.

    >>> with tempfile.TemporaryDirectory() as tmpdir:
    ...     expand_path('$PY_TEST_VAR2/*.txt') # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    ValueError: Environment variable PY_TEST_VAR2 is not defined

    """
    template = string.Template(path)
    try:
        expanded_path = template.substitute(os.environ)
    except KeyError as e:
        raise ValueError(f"Environment variable {e} is not defined")

    paths = glob.glob(expanded_path)
    paths = [str(pathlib.Path(path).resolve()) for path in paths]
    paths = [os.path.relpath(path) for path in paths]
    return paths


################################################################################
# main function
################################################################################

def generate_file(
        pattern_to_generate='$SERIES/$STORY/outline.json',
        *,
        prompt_dir='prompts',
        config_path='prompts/config.yaml',
        overwrite=False,
        print_prompt=False,
        print_states=False,
        ):

    llm = LLM()

    # load config file
    import yaml
    with open(config_path) as fin:
        full_config = yaml.safe_load(fin)
    assert(pattern_to_generate in full_config)
    config = full_config[pattern_to_generate]

    # compute the variables
    states = [{}]
    for var, expr in config.get('variables', {}).items():

        states0 = states
        states = []
        for state in states0:

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
                    env={**os.environ, **state},
                    )
                if result.returncode != 0:
                    logger.error(f"result.returncode={result.returncode}")
                    logger.error(f"var={var}")
                    logger.error(f"expr={expr}")
                    logger.error(f"result.stdout={result.stdout}")
                    logger.error(f"result.stderr={result.stderr}")
                    sys.exit(1)
                vals = result.stdout

            # lists are separated by null characters;
            # for each entry in the list,
            # we will add a new state with the entry added
            for val in vals.split('\0'):

                # don't add val to the states list when it is empty;
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

                # add the state
                state1 = copy.copy(state)
                state1[var] = val
                states.append(state1)

    # print states debug information
    logger.debug(f'len(states) = {len(states)}')
    if print_states:
        import pprint
        pprint.pprint(states)
        return

    # loop over each state and run the processing code for the state
    for i, state in enumerate(states):

        # build with a custom command
        if config.get('cmd'):
            result = subprocess.run(
                config['cmd'],
                shell=True,
                capture_output=True,
                text=True,
                executable="/bin/bash",
                env={**os.environ, **state},
                )
            if result.returncode != 0:
                logger.error(f"result.returncode={result.returncode}")
                logger.error(f"result.stdout={result.stdout}")
                logger.error(f"result.stderr={result.stderr}")
                sys.exit(1)

        # build the target with the LLM
        else:

            logging.debug(f'state loop i={i}')

            # update the environment variables with the current state
            for k, v in state.items():
                os.environ[k] = v

            # compute the dependencies
            all_paths = []
            deps = config['dependencies'].split()
            for dep_path in deps:
                new_paths = expand_path(dep_path)
                if not new_paths:
                    logger.warning(f'no paths found for dep_path={dep_path}')
                all_paths.extend(new_paths)
            logger.debug(f"all_paths={all_paths}")

            # compute files_prompt
            files_prompt = '<documents>\n'
            for path in all_paths:
                with open(path) as fin:
                    files_prompt += f'''<document path="{path}">
{fin.read().strip()}
</document>
'''
            files_prompt += '</documents>'

            # compute the instructions prompt
            filename = os.path.basename(pattern_to_generate)
            _, extension = os.path.splitext(filename)

            if 'prompt_file' in config:
                prompt_path = config['prompt_file']
            else:
                prompt_path = os.path.join(prompt_dir, filename)
            with open(prompt_path) as fin:
                prompt_cmd = fin.read()
                prompt_cmd = process_template(prompt_cmd)
            
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
            path_to_generate = os.path.expandvars(pattern_to_generate)
            logger.debug(f"path_to_generate={path_to_generate}")
            dirname = os.path.dirname(path_to_generate)
            os.makedirs(dirname, exist_ok=True)
            mode = 'wt' if overwrite else 'xt'
            try:
                with open(path_to_generate, mode) as fout:
                    fout.write(llm.text(prompt))
            except FileExistsError:
                logging.warning(f'File {path_to_generate} exists; skipping')

if __name__ == '__main__':
    #logger.setLevel(logging.DEBUG)
    logger.setLevel(logging.INFO)
    clize.run(generate_file)
