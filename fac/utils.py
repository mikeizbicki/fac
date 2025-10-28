import glob
import os
import pathlib
import re
import subprocess
import tempfile


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


def substitute_vars_list(template_str, vars_dict=None):
    """
    Substitute variables in a string with values from a dictionary, returning a list.

    If a variable contains newlines, it's split and creates multiple output strings.
    If no variables contain newlines, returns a single-item list.

    >>> substitute_vars_list('Path is $VAR1', {'VAR1': 'value1'})
    ['Path is value1']
    >>> substitute_vars_list('Path is $VAR1', {'VAR1': 'line1\\nline2'})
    ['Path is line1', 'Path is line2']
    >>> substitute_vars_list('$VAR1 and $VAR2', {'VAR1': 'a\\nb', 'VAR2': '1\\n2'})
    ['a and 1', 'a and 2', 'b and 1', 'b and 2']

    >>> substitute_vars_list('Path is $VAR1 and $VAR2', {})
    ['Path is $VAR1 and $VAR2']
    >>> substitute_vars_list('$VAR1 and $VAR2', {'VAR1': 'a\\nb'})
    ['a and $VAR2', 'b and $VAR2']
    """
    if vars_dict is None:
        vars_dict = {}

    results = [template_str]

    for var, value in vars_dict.items():
        new_results = []
        for result in results:
            if f'${var}' in result or f'${{{var}}}' in result:
                lines = str(value).split('\n')
                for line in lines:
                    new_str = result.replace(f'${var}', line).replace(f'${{{var}}}', line)
                    new_results.append(new_str)
            else:
                new_results.append(result)
        results = new_results

    return results


def substitute_vars_with_multiline(template_str, vars_dict=None):
    """
    Substitute variables in a string, but leave multiline variables unsubstituted.
    
    Returns a tuple of (substituted_string, multiline_vars_dict).
    Variables with newlines are not substituted and are returned in the dict.
    
    >>> substitute_vars_with_multiline('Path is $VAR1', {'VAR1': 'value1'})
    ('Path is value1', {})
    >>> substitute_vars_with_multiline('Path is $VAR1', {'VAR1': 'line1\\nline2'})
    ('Path is $VAR1', {'VAR1': ['line1', 'line2']})
    >>> substitute_vars_with_multiline('$VAR1 and $VAR2', {'VAR1': 'single', 'VAR2': 'a\\nb'})
    ('single and $VAR2', {'VAR2': ['a', 'b']})
    >>> substitute_vars_with_multiline('$VAR1 and $VAR2', {'VAR1': 'single', 'VAR2': 'a\\nb', 'VAR3': 'a\\nb'})
    ('single and $VAR2', {'VAR2': ['a', 'b']})
    >>> substitute_vars_with_multiline('$VAR1 and $VAR2', {'VAR1': 'single', 'VAR2': 'a\\nb', 'VAR3': 'a'})
    ('single and $VAR2', {'VAR2': ['a', 'b']})
    >>> substitute_vars_with_multiline('Path is $VAR1 and $VAR2', {'VAR1': 'value1'})
    ('Path is value1 and $VAR2', {})
    >>> substitute_vars_with_multiline('Path is $VAR1 and $VAR2', {})
    ('Path is $VAR1 and $VAR2', {})
    >>> substitute_vars_with_multiline('Path is $VAR1 and $VAR2', {'VAR3': 'a\\nb'})
    ('Path is $VAR1 and $VAR2', {})
    >>> substitute_vars_with_multiline('Path is $VAR1 and $VAR2', {'VAR3': 'a'})
    ('Path is $VAR1 and $VAR2', {})
    """
    if vars_dict is None:
        vars_dict = {}
    
    result_str = template_str
    multiline_vars = {}
    
    for var, value in vars_dict.items():
        if f'${var}' in template_str or f'${{{var}}}' in template_str:
            value_str = str(value)
            if '\n' in value_str:
                multiline_vars[var] = value_str.split('\n')
            else:
                result_str = result_str.replace(f'${var}', value_str)
                result_str = result_str.replace(f'${{{var}}}', value_str)
    
    return result_str, multiline_vars


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
            raise TemplateProcessingError(result.returncode, result.stdout, result.stderr, env_vars)
        return result.stdout.strip()

    finally:
        # Ensure the temporary file is removed
        if os.path.exists(script_path):
            os.unlink(script_path)


class TemplateProcessingError(Exception):
    """Exception raised when template processing fails."""

    def __init__(self, returncode, stdout, stderr, env_vars):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.env_vars = env_vars
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


def expand_vars_on_newlines(env_vars):
    r'''
    Takes a dictionary where values may contain newline characters and returns
    a list of dictionaries representing all possible combinations where each
    newline-separated value is treated as an alternative.
    
    >>> expand_vars_on_newlines({})
    [{}]
    >>> expand_vars_on_newlines({'a': 'test'})
    [{'a': 'test'}]
    >>> expand_vars_on_newlines({'a': 'hello\nworld'})
    [{'a': 'hello'}, {'a': 'world'}]
    >>> expand_vars_on_newlines({'a': 'one\ntwo\nthree'})
    [{'a': 'one'}, {'a': 'two'}, {'a': 'three'}]

    >>> expand_vars_on_newlines({'a': 'test', 'b': 'prueba'})
    [{'a': 'test', 'b': 'prueba'}]
    >>> expand_vars_on_newlines({'a': 'hello\nworld', 'b': 'prueba'})
    [{'a': 'hello', 'b': 'prueba'}, {'a': 'world', 'b': 'prueba'}]
    >>> expand_vars_on_newlines({'a': 'hello\nworld', 'b': 'hola\nmundo'})
    [{'a': 'hello', 'b': 'hola'}, {'a': 'hello', 'b': 'mundo'}, {'a': 'world', 'b': 'hola'}, {'a': 'world', 'b': 'mundo'}]

    >>> expand_vars_on_newlines({'a': 'x\ny', 'b': '1\n2'})
    [{'a': 'x', 'b': '1'}, {'a': 'x', 'b': '2'}, {'a': 'y', 'b': '1'}, {'a': 'y', 'b': '2'}]

    >>> expand_vars_on_newlines({'PATH': '/bin\n/usr/bin', 'HOME': '/root'})
    [{'PATH': '/bin', 'HOME': '/root'}, {'PATH': '/usr/bin', 'HOME': '/root'}]
    '''
    # Split values on newlines and create lists
    split_vars = {k: v.split('\n') if isinstance(v, str) else [v]
                  for k, v in env_vars.items()}

    # Generate all combinations
    from itertools import product
    keys = list(split_vars.keys())
    combinations = product(*[split_vars[k] for k in keys])

    return [dict(zip(keys, combo)) for combo in combinations]


def variable_dictionary_resolve(env_vars):
    '''
    The input dictionary represents a set of variable assignments.
    Some variables may be assigned to other variables (using $VAR shell notation).
    This function returns a resolved dictionary where all of these substitutions have occurred.

    # Chain resolution
    >>> variable_dictionary_resolve({'a': '1', 'b': '$a', 'c': '$b'})
    {'a': '1', 'b': '1', 'c': '1'}

    # Multiple variables in one value
    >>> variable_dictionary_resolve({'a': '1', 'b': '2', 'c': '$a$b'})
    {'a': '1', 'b': '2', 'c': '12'}
    >>> variable_dictionary_resolve({'a': 'hello', 'b': 'world', 'c': '$a $b'})
    {'a': 'hello', 'b': 'world', 'c': 'hello world'}

    # Partial matches
    >>> variable_dictionary_resolve({'a': '1', 'ab': '$a2'})
    {'a': '1', 'ab': '$a2'}
    >>> variable_dictionary_resolve({'a': '1', 'b': 'prefix$a'})
    {'a': '1', 'b': 'prefix1'}

    # Undefined variables (remain as-is)
    >>> variable_dictionary_resolve({'a': '$undefined'})
    {'a': '$undefined'}

    # Empty dictionary
    >>> variable_dictionary_resolve({})
    {}
    '''
    resolved = env_vars.copy()
    changed = True

    # Keep resolving until no more substitutions are made
    while changed:
        changed = False
        for key, value in resolved.items():
            # Find all $VAR patterns in the value
            matches = re.findall(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', str(value))
            new_value = str(value)

            for var_name in matches:
                if var_name in resolved:
                    # Replace $var_name with its resolved value
                    new_value = new_value.replace(f'${var_name}', str(resolved[var_name]))
                    changed = True

            resolved[key] = new_value

    return resolved
