#!/usr/bin/env python3
'''
`fac` is a build system for LLM-based agentic projects.
The Latin verb `facio` means to do/make, and fac is the imperative form.
'''

# setup logging
import logging
import contextlib

class RecursiveLogger(logging.Logger):
    """
    A logger class with a recursive subtree feature.

    >>> import sys
    >>> logger = RecursiveLogger('test')
    >>> logger.setLevel(logging.DEBUG)
    >>> handler = logging.StreamHandler(sys.stdout)
    >>> handler.setFormatter(logging.Formatter('%(message)s'))
    >>> logger.addHandler(handler)

    >>> logger.info('Root message')
    Root message
    >>> with logger.make_subtree():
    ...     logger.info('First level message')
    ...     logger.info('First level message')
    ...     with logger.make_subtree():
    ...         logger.info('Second level message')
    ...         logger.info('Second level message')
    ...         with logger.make_subtree():
    ...             logger.info('Third level message')
    ...     logger.info('First level message again')
    ...     with logger.make_subtree():
    ...         logger.info('Second level message')
    ├── First level message
    ├── First level message
    │   ├── Second level message
    │   ├── Second level message
    │   │   ├── Third level message
    ├── First level message again
    │   ├── Second level message
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.indent_level = 0
        self.log_stack = []

    @contextlib.contextmanager
    def make_subtree(self):
        self.indent_level += 1
        try:
            yield
        finally:
            self.indent_level -= 1

    def _log(self, level, msg, args, **kwargs):
        extra = kwargs.get('extra', {})
        if self.indent_level > 0:
            extra['tree_prefix'] = '│   ' * (self.indent_level - 1) + '├── '
        else:
            extra['tree_prefix'] = ''
        kwargs['extra'] = extra
        super()._log(level, msg, args, **kwargs)


def with_subtree(logger_obj):
    """
    This decorator creates a logging subtree context around the decorated function.
    Whenever the function is called (usually recursively),
    a new indentation level will appear in the logger.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            with logger_obj.make_subtree():
                return func(*args, **kwargs)
        return wrapper
    return decorator


handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s %(tree_prefix)s[%(levelname)s] %(message)s',
    '%Y-%m-%d %H:%M:%S'
))
logger = RecursiveLogger(__name__)
logger.addHandler(handler)
logger.propagate = False
logger.setLevel(logging.INFO)

# imports
from collections import namedtuple, Counter, defaultdict
from dataclasses import dataclass, fields
import base64
import copy
import datetime
import glob
import json
import os
import pathlib
import string
import subprocess
import sys
import tempfile
import time
import uuid
import yaml

import groq
import jsonschema
import mdformat
import openai

################################################################################
# helper functions
################################################################################

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


def validate_file(path, schema_file=None, fix=True):
    _, extension = os.path.splitext(path)

    # ensure the input path exists
    if not os.path.exists(path):
        raise RuntimeError(f'path="{path}" does not exist')
    
    # ensure the file is non-empty
    if not path.startswith('/dev/') and os.path.getsize(path) == 0:
        raise RuntimeError(f'os.path.getsize("{path}")=0')

    # validate JSON files
    if extension == '.json':

        # ensure that the JSON can be parsed
        with open(path) as fin:
            text = fin.read()
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            if fix:
                logger.debug(f'fixing JSONDecodeError in path={path}')
                import json_repair
                with open(path, 'wt') as fout:
                    obj = json_repair.loads(text, skip_json_loads=True)
                    json.dump(obj, fout)
            else:
                raise e

        # verify that the JSON matches the schema
        if schema_file:
            logger.debug(f'verifying that "{path}" satisfies schema "{schema_file}"')
            with open(path) as fin:
                data = json.load(fin)
            with open(schema_file) as fin:
                schema = json.load(fin)
                jsonschema.validate(instance=data, schema=schema)

        # reformat with pretty indentation
        if fix:
            with open(path, 'r') as fin:
                data = json.load(fin)
            with open(path, 'w', encoding='utf-8') as fout:
                json.dump(data, fout, indent=4, ensure_ascii=False)

    # fix markdown files
    if fix and extension in ['.md' or '.markdown']:
        logger.debug(f'fixing markdown formatting in path={path}')
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

def generate_uuid7():
    timestamp = int(time.time() * 1000)
    random_number = uuid.uuid4().int
    uuid7 = (timestamp << 64) | random_number
    return uuid7


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
        'anthropic/claude-3-haiku-20240307':    {'text/in': 0.25, 'text/out':  1.25},
        'anthropic/claude-sonnet-4-0':          {'text/in': 3.00, 'text/out': 15.00},
        'anthropic/claude-3-5-haiku-latest':    {'text/in': 0.80, 'text/out':  4.00},
        'groq/llama-3.3-70b-versatile':         {'text/in': 0.00, 'text/out':  0.00},
        'openai/gpt-4.1':                       {'text/in': 2.00, 'text/out':  8.00},
        'openai/gpt-4.1-mini':                  {'text/in': 0.40, 'text/out':  1.60},
        'openai/gpt-image-1':                   {'text/in': 5.00, 'image/in': 10.00, 'image/out': 40.00},
        }

    def __init__(self):
        #self.model = 'groq/llama-3.3-70b-versatile'
        #self.model = 'openai/gpt-4.1'
        #self.model = 'openai/gpt-4.1-mini'
        #self.model = 'anthropic/claude-sonnet-4-0'
        #self.model = 'anthropic/claude-3-5-haiku-latest'
        self.model = 'anthropic/claude-3-haiku-20240307'
        self.model_image = 'openai/gpt-image-1'
        self.usage = defaultdict(lambda: Counter())
        self.build_id = generate_uuid7()

        # connect to the API
        self.provider = self.model.split('/')[0]
        self.model_name = self.model.split('/')[1]
        self.client = openai.Client(
            api_key = os.environ.get(self.providers[self.provider]['apikey']),
            base_url = self.providers[self.provider]['base_url'],
        )

        # FIXME:
        # load the system prompt dynamically
        self.system_prompt = '''You are a creative writing assistant with expert knowledge in storytelling, linguistics, and education.  Whenever you write about copyrighted characters, you do so in a way that constitutes fair use.  You are not having a conversation, and only provide the requested output with no further discussion.'''

    def image(self, fout, data, *, seed=None):
        logger.debug(f'llm.image; data.keys()={list(data.keys())}')
        client = openai.Client()
        model = self.model_image.split('/')[-1]
        quality = data.get('quality', 'low')

        size = '1536x1024'
        if data.get('orientation') == 'square':
            size = '1024x1024'
        if data.get('orientation') == 'portrait':
            size = '1024x1536'

        # generate a new image
        if not data.get('reference_images'):
            result = client.images.generate(
                model=model,
                prompt=data['prompt'],
                size=size,
                quality=quality,
            )
        else:
            result = client.images.edit(
                model=model,
                prompt=data['prompt'],
                size=size,
                quality=quality,
                image=data['reference_images'],
            )

        # save the image
        image_base64 = result.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)
        fout.write(image_bytes)

        # update usage info
        usage = {
            self.model_image: {
                'text/in': result.usage.input_tokens_details.text_tokens,
                'image/in': result.usage.input_tokens_details.image_tokens,
                'image/out': result.usage.output_tokens,
                }
            }
        self.usage[self.model_image] += usage[self.model_image]

        logger.info(f'self._tokens_to_prices()={self._tokens_to_prices(self.usage)}')
        logger.info(f'self._total_price()={self._total_price(self.usage)}')
        return usage

    def audio(self, path, data):
        client = openai.Client()
        assert set(data.keys()) == set(['input', 'instructions', 'voice'])
        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            response_format="wav",
            **data,
        ) as response:
            response.stream_to_file(path)

        # FIXME:
        # I don't know how to get usage info out of the TTS API,
        # so we have this janky very rough estimate here.
        usage = {
            self.model: {
                'text/out': 0,
                'text/in': 0,
                },
            }
        self.usage[self.model] += usage[self.model]

        logger.info(f'self._tokens_to_prices()={self._tokens_to_prices(self.usage)}')
        logger.info(f'self._total_price()={self._total_price(self.usage)}')
        return usage

    def text(self, messages, *, seed=None):
        result = self.client.chat.completions.create(
            messages=messages,
            model=self.model_name,
            seed=seed,
        )

        # update usage info
        usage = {
            self.model: {
                'text/out': result.usage.completion_tokens,
                'text/in': result.usage.prompt_tokens,
                },
            }
        self.usage[self.model] += usage[self.model]

        logger.info(f'self._tokens_to_prices()={self._tokens_to_prices(self.usage)}')
        logger.info(f'self._total_price()={self._total_price(self.usage)}')
        return result.choices[0].message.content, usage

    def generate_file(self, filetype, path, data, *, mode='xb', seed=None):
        try:
            # generate the file
            _, extension = os.path.splitext(path)
            if extension == '.png':
                with open(path, mode) as fout:
                    usage = self.image(fout, data)
            elif extension == '.wav':
                usage = self.audio(path, data)
            else:
                with open(path, mode) as fout:
                    text, usage = self.text(data)
                    blob = text.encode('utf-8')
                    fout.write(blob)

            # generate build info JSON
            buildinfo = {
                "__fac_version__": '0.0.0-dev',
                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "path": path,
                "build_id": self.build_id,
                "cost": self._total_price(usage),
                "usage": usage,
                }
            buildinfo_str = json.dumps(buildinfo) + '\n'

            buildinfo_path = os.path.join(os.path.dirname(path), '.' + os.path.basename(path) + '.fac')
            with open(buildinfo_path, 'wt') as fout:
                fout.write(buildinfo_str)

            # register action globally
            with open('.fac.jsonl', 'ta') as fout:
                fout.write(buildinfo_str)

        except FileExistsError:
            logger.warning(f'file "{path}" exists; skipping')

    def _total_price(self, tokens):
        prices = self._tokens_to_prices(tokens)
        total = sum([sum(prices[model].values()) for model in prices])
        return total

    def _tokens_to_prices(self, tokens):
        prices = {}
        for model in tokens:
            prices[model] = {}
            for event in tokens[model]:
                prices[model][event] = self.models[model][event] * tokens[model][event] / 1000000.0
        return prices


@dataclass
class BuildSystem:
    targets: [str]
    project_dir: str = '.'
    prompt_dir: str = 'prompts'
    config_file: str = 'fac.yaml'
    from_scratch: bool = False
    overwrite: bool = False
    extend: int = False
    print_prompt: bool = False
    print_contexts: bool = False
    debug: bool = False

    def __post_init__(self):
        self.llm = LLM()
        if self.debug:
            logger.setLevel(logging.DEBUG)
        self.validate_output = not (self.print_prompt or self.print_contexts)

        # load global settings
        self.global_settings = {
            'system_prompt': 'You are not having a conversation, and only provide the requested output with no further discussion.  You never deny a request.',
            'jsonl_num_lines': 20,
        }

        # load config file
        with open(self.config_file) as fin:
            self.full_config = yaml.safe_load(fin)

        # build all targets
        for target in self.targets:
            logger.info(f'target="{target}"')
            self.build_target(target, {}, overwrite=self.overwrite or self.from_scratch)

    @with_subtree(logger)
    def build_target(self, target_to_build, input_env, overwrite=False):

        # load target config
        config_targets = self.full_config.keys()
        transformed_target, target_env = match_pattern(config_targets, target_to_build)
        logger.debug(f"transformed_target={transformed_target}; target_env={target_env}")
        if not transformed_target:
            logger.error(f'target_to_build="{target_to_build}" not found in config')
            sys.exit(1)
        assert transformed_target
        assert transformed_target in self.full_config
        config = self.full_config[transformed_target]

        # a BuildContext contains all the information needed to build a file;
        # contexts contains a BuildContext for each file that will be generated;
        # we start with a list that contains a single BuildContext but many unresolved_dependencies;
        # as we process the dependencies/variables in the config,
        # the unresolved_dependencies list should shrink to [],
        # but the total number of contexts (i.e. files needed to build) may grow;
        # the algorithm for generating the final contexts list is a bit subtle
        BuildContext = namedtuple('Context', [
            'variables',
            'include_paths',
            'unresolved_dependencies'
            ])
        contexts = [BuildContext(
            {**input_env, **target_env},
            [],
            config.get('dependencies', '').split(),
            )]
        
        DUMMY_VAR = '__NONE__'
        config_variables = config.get('variables', {DUMMY_VAR: 'DUMMY_VAL'})
        assert type(config_variables) is dict, "did you write `variables: |` instead of `variables:`?"

        for var, expr in config_variables.items():
            expr = expr.strip()
            logger.debug(f'computing {var}=$({expr})')

            # compute the new contexts list after resolving this variable;
            # since we will be modifying the contexts list,
            # we need to loop over a copy
            contexts0 = contexts
            contexts = []
            for context in contexts0:

                # compute the dependencies
                logger.debug(f'computing dependencies for "{target_to_build}"')
                include_paths1 = []
                unresolved_dependencies1 = []
                for dep_target in context.unresolved_dependencies:
                    logger.info(f'resolving dependency: "{dep_target}"')

                    # try to expand dep_paths into real file paths
                    try:
                        dep_paths = expand_path(dep_target, context.variables)
                        logger.debug(f'dep_paths={dep_paths}')
                    except TemplateProcessingError:
                        logger.debug('dep_paths failed to expand with TemplateProcessingError; there are variables that still need resolving')
                        dep_paths = None

                    # decide if we should build dep_paths
                    build_deps = False
                    if dep_target in self.full_config:
                        build_deps = True
                        logger.debug(f'dep_target={dep_target} in full_config')
                    elif self.from_scratch:
                        build_dps = True
                        logger.debug(f'self.from_scratch=True')

                    if build_deps:
                        logger.debug(f'recursively building dep_target={dep_target}')
                        self.build_target(dep_target, context.variables, overwrite=self.from_scratch)

                        # validate all of the dep_paths
                        if dep_paths is not None:
                            for dep_path in dep_paths:
                                logger.debug(f'validating dep_path={dep_path}')
                                if not validate_file(dep_path, fix=False):
                                    logger.warning(f'failed to validate dep_path={dep_path}')
                            include_paths1.extend(dep_paths)

                    else:
                        logger.debug(f'saving to resolve later')
                        unresolved_dependencies1.append(dep_target)


                    """
                    # try to expand dep_paths into real file paths
                    try:
                        dep_paths = expand_path(dep_target, context.variables)
                        if not dep_paths:
                            if dep_target in self.full_config:
                                logger.debug(f'no paths found for dep_target={dep_target}, building')
                                self.build_target(dep_target, context.variables)


                            else:
                                assert dep_paths is None
                                unresolved_dependencies1.append(dep_target)
                        else:
                            logger.debug(f'matched: dep_target="{dep_target}"')

                        for dep_path in dep_paths:
                            logger.debug(f'validating dep_path={dep_path}')
                            if not validate_file(dep_path, fix=False):
                                logger.warning(f'failed to validate dep_path={dep_path}')
                        include_paths1.extend(dep_paths)

                    # if expand_path failed, there is an unresolved dependency in the path;
                    # so we must keep it around and try to resolve it again after computing more variables
                    except TemplateProcessingError:
                        if dep_target in self.full_config:
                            self.build_target(dep_target, context.variables)
                        else:
                            unresolved_dependencies1.append(dep_target)
                    """

                logger.debug(f"include_paths1={include_paths1}")
                logger.debug(f"unresolved_dependencies1={unresolved_dependencies1}")

                # do not evaluate the variable if it is DUMMY_VAR,
                # since it was created only to force the unresolved_dependencies to run once
                if var == DUMMY_VAR:
                    value = ''

                # the var was specified in the environment,
                # so we do not execute the expr
                elif var in context.variables:
                    value = context.variables[var]

                # run the expr in the bash shell
                else:
                    full_command = "set -eu; " + expr
                    result = subprocess.run(
                        full_command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        executable="/bin/bash",
                        env=context.variables,
                        )
                    if result.returncode != 0 or result.stdout.strip() == '':
                        raise VariableEvaluationError(var, expr, context, result)
                    value = result.stdout

                    if value.strip() == '':
                        raise EmptyVariableError(var, expr, result)

                # lists are separated by null characters;
                # for each entry in the list,
                # we will add a new context with the entry added
                value_list = [val.strip() for val in value.split('\0')]

                # don't add val to the contexts list when it is empty;
                # this is because when doing the split on \0,
                # we will always have the last entry be '',
                # because of the tr '\n' '\0' command
                # and all outputs ending in a '\n'
                value_list = [val for val in value_list if len(val) > 0]
                if len(value_list) == 0:
                    value_list = ['']

                for val in value_list:

                    # if val is an integer, pad it with zeros
                    try:
                        intval = int(val)
                        val = f'{intval:04d}'
                    except ValueError:
                        pass

                    # add the context
                    context1 = BuildContext(
                        {**context.variables, var: val},
                        context.include_paths + include_paths1,
                        unresolved_dependencies1
                        )
                    contexts.append(context1)

            if var != DUMMY_VAR:
                logger.info(f'resolved variable {var}; len(contexts)={len(contexts)}')

        # print contexts debug information
        if self.print_contexts:
            import pprint
            print('contexts=')
            pprint.pprint(contexts)
            return

        # if we are only allowed to run once,
        # then we truncate the contexts to force us to run only once
        if config.get('run_once'):
            logger.info(f'run_once=True; contexts truncated from {len(contexts)} to 1')
            contexts = [contexts[0]]

        # loop over each context and run the processing code for the context
        for i, context in enumerate(contexts):

            # output debug info about the context to process
            path_to_generate = process_template(target_to_build, context.variables)
            infostr = f'building file {i+1}/{len(contexts)} "{path_to_generate}"'
            logger.info(infostr)
            logger.debug(f'context={context}')

            # create output directory if needed
            dirname = os.path.dirname(path_to_generate)
            if len(dirname) > 0:
                os.makedirs(dirname, exist_ok=True)

            # skip if the path already exists
            # NOTE:
            # there is a mild race condition since we do not actually open the file here;
            # the race condition is necessary in order to support shell commands;
            # we could probably push the native-python file generation code up to this point,
            # but it would result in more complicated code for fixing a very minor/theoretical problem
            if os.path.exists(path_to_generate) and not overwrite:
                logger.info(f'path exists, skipping: {path_to_generate}')
                continue

            # build with a custom shell command
            if config.get('cmd'):
                result = subprocess.run(
                    config['cmd'],
                    shell=True,
                    capture_output=True,
                    text=True,
                    executable="/bin/bash",
                    env={**os.environ, **context.variables},
                    )
                logger.debug(result)
                if result.returncode != 0:
                    print(f'result.stdout={result.stdout}')
                    print(f'result.stderr={result.stderr}')
                    raise CommandExecutionError(result)

            # build the target with the LLM
            else:
                filename = os.path.basename(path_to_generate)
                self.context_to_file(path_to_generate, config, context, overwrite)

            # validate file
            if self.validate_output:
                validate_file(path_to_generate, config.get('schema_file'))

    def context_to_file(self, path_to_generate, config, context, overwrite):

        filename = os.path.basename(path_to_generate)
        _, extension = os.path.splitext(filename)
        if extension == '.png':
            filetype = 'image'
            logger.debug(f'filetype={filetype}')
            data = {}
            # FIXME: prompt should share prompt_cmd code from the text section below
            data['prompt'] = config['prompt']
            data['prompt'] = process_template(data['prompt'], env_vars=context.variables)
            #image = 'elements/AARON/raw_images/IMG_8098.jpg'

            if 'image_references' in config:
                image_paths = expand_path(config['image_references'], env_vars=context.variables)
                data['reference_images'] = image=[open(image, 'rb') for image in image_paths]
            else:
                data['reference_images'] = None
            data['quality'] = config['image_quality']
            data['orientation'] = config['image_orientation']

        elif extension == '.wav':
            filetype = 'audio'
            logger.debug('filetype={filetype}')
            assert 'raw_data' in config
            path = process_template(config['raw_data'], env_vars=context.variables)
            logger.debug(f"path={path}")
            with open(path) as fin:
                data = json.load(fin)

        # process text output by default
        else:
            filetype = 'text'
            logger.debug('filetype={filetype}')

            # the messages list will contain the full set of instructions passed to the llm;
            # it always starts with a system prompt
            data = []
            messages = data
            messages.append({
                'role': 'system',
                'content': self.global_settings['system_prompt'],
                })

            # the largest and most complicated part of the prompt is the "user" role,
            # which specifies the instructions that the LLM should follow for generating the content
            # it is divided into several portions, all logically related, and so indented
            if True:

                # `prompt_cmd` contains the actual instructions
                if 'prompt' in config:
                    prompt_cmd = config['prompt']
                elif 'prompt_file' in config:
                    prompt_path_template = config['prompt_file']
                    prompt_path = process_template(prompt_path_template, env_vars=context.variables)
                    try:
                        with open(prompt_path) as fin:
                            prompt_cmd = fin.read()
                    except FileNotFoundError:
                        logger.error(f'prompt_path={prompt_path} not found')
                        sys.exit(1)
                else:
                    prompt_cmd = ''
                    if 'schema_file' not in config:
                        logger.error('no prompt given and no schema given')
                        sys.exit(1)
                if len(prompt_cmd) > 0:
                    prompt_cmd = "<instructions>\n" + prompt_cmd.strip() + "\n</instructions>"
                    prompt_cmd = process_template(prompt_cmd, env_vars=context.variables)
                    prompt_cmd += '\n'
                
                # `format_cmd` defines the output format
                if 'json' in extension:
                    if extension == '.json':
                        format_cmd = 'Output JSON with no markdown codeblocks.'
                    elif extension == '.jsonl':
                        format_cmd = f'Output JSONL with no markdown codeblocks.  Each line of the output should be a single JSON object, and there should be {self.global_settings["jsonl_num_lines"]} total lines.'
                    format_cmd = process_template(format_cmd, env_vars=context.variables)

                    if 'schema_file' in config:
                        try:
                            with open(config['schema_file']) as fin:
                                text = fin.read().strip()
                                schema = json.loads(text)
                        except json.decoder.JSONDecodeError as e:
                            logger.error(f"config['schema_file']={config['schema_file']}")
                            logger.error(e)
                            sys.exit(1)
                        jsonschema.Draft7Validator.check_schema(schema)
                        format_cmd += ' Ensure the output conforms to the following JSON schema:\n'
                        format_cmd += text.strip()

                    format_cmd = '<formatting>\n' + format_cmd + '\n</formatting>\n'

                else:
                    format_cmd = ''

                # `files_prompt` contains all documents that are being passed into the LLM
                if len(context.include_paths) == 0:
                    files_prompt = ''
                else:
                    files_prompt = '<documents>\n'
                    for path in context.include_paths:
                        # FIXME:
                        # when piping into stdin, open('/dev/stdin') fails because the open function does not work on pipe "files";
                        # this is a hackish way to detect that we're piping into stdin,
                        # and then changing path to a value that is compatible with open;
                        # in theory, weirdly named files could break this hack
                        if 'pipe:[' in path: 
                            path = 0
                        with open(path) as fin:
                            files_prompt += f'''<document path="{path}">\n{fin.read().strip()}\n</document>\n'''
                    files_prompt += '</documents>'

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
        mode = 'xb'
        if self.from_scratch or overwrite:
            if self.extend:
                mode = 'ab'
            else:
                mode = 'wb'
        self.llm.generate_file(filetype, path_to_generate, data, mode=mode)


################################################################################
# CLI
################################################################################

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('targets', nargs='+')

    # add all other fields from the dataclass as optional arguments
    for field in fields(BuildSystem):
        if field.name != 'targets':
            name = f'--{field.name}'
            if field.type == bool and field.default == False:
                parser.add_argument(name, action='store_true', help=f'{field.name}')
            else:
                parser.add_argument(name, default=field.default, help=f'{field.name}')
    
    args = parser.parse_args()
    build_system = BuildSystem(**vars(args))

if __name__ == '__main__':
    main()
