from collections import defaultdict, deque
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
    If any variable is empty, returns an empty list.

    Basic substitution:
    >>> substitute_vars_list('Hello $name', {'name': 'world'})
    ['Hello world']
    >>> substitute_vars_list('$greeting $name', {'greeting': 'Hi', 'name': 'Alice'})
    ['Hi Alice']
    >>> substitute_vars_list('${var1}_${var2}', {'var1': 'prefix', 'var2': 'suffix'})
    ['prefix_suffix']

    Multiline variables:
    >>> substitute_vars_list('Name: $name', {'name': 'Alice\\nBob'})
    ['Name: Alice', 'Name: Bob']
    >>> substitute_vars_list('$x-$y', {'x': 'a\\nb', 'y': '1\\n2'})
    ['a-1', 'a-2', 'b-1', 'b-2']

    Edge cases with empty/whitespace:
    >>> substitute_vars_list('Value: $var', {'var': ''})
    []
    >>> substitute_vars_list('$a and $b', {'a': 'hello', 'b': ''})
    []
    >>> substitute_vars_list('$var', {'var': '  \\n  \\nvalid\\n  '})
    ['valid']

    No substitutions:
    >>> substitute_vars_list('No variables here', {})
    ['No variables here']
    >>> substitute_vars_list('$missing stays', {'other': 'value'})
    ['$missing stays']
    >>> substitute_vars_list('$found and $missing', {'found': 'exists'})
    ['exists and $missing']

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
                    line = line.strip()
                    if line:  # Only append if line is non-empty
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


def expand_vars_on_newlines(env_vars, filter_variables=None):
    r'''
    Takes a dictionary where values may contain newline characters and returns
    a list of dictionaries representing all possible combinations where each
    newline-separated value is treated as an alternative.

    If filter_variables is provided, variables in that list will cause the
    function to return [] if they have no valid values.

    Basic cases:
    >>> expand_vars_on_newlines({})
    [{}]
    >>> expand_vars_on_newlines({'a': 'test'})
    [{'a': 'test'}]

    Single variable with multiple values:
    >>> expand_vars_on_newlines({'a': 'hello\nworld'})
    [{'a': 'hello'}, {'a': 'world'}]
    >>> expand_vars_on_newlines({'a': 'one\ntwo\nthree'})
    [{'a': 'one'}, {'a': 'two'}, {'a': 'three'}]

    Multiple variables - no newlines:
    >>> expand_vars_on_newlines({'a': 'test', 'b': 'prueba'})
    [{'a': 'test', 'b': 'prueba'}]

    Multiple variables - combinations:
    >>> expand_vars_on_newlines({'a': 'hello\nworld', 'b': 'prueba'})
    [{'a': 'hello', 'b': 'prueba'}, {'a': 'world', 'b': 'prueba'}]
    >>> expand_vars_on_newlines({'a': 'x\ny', 'b': '1\n2'})
    [{'a': 'x', 'b': '1'}, {'a': 'x', 'b': '2'}, {'a': 'y', 'b': '1'}, {'a': 'y', 'b': '2'}]

    Whitespace handling:
    >>> expand_vars_on_newlines({'a': ' hello \n world '})
    [{'a': 'hello'}, {'a': 'world'}]
    >>> expand_vars_on_newlines({'a': 'test\n  \nmore'})
    [{'a': 'test'}, {'a': 'more'}]

    Empty variables (default behavior - kept in results):
    >>> expand_vars_on_newlines({'a': ''})
    [{}]
    >>> expand_vars_on_newlines({'a': '   '})
    [{}]
    >>> expand_vars_on_newlines({'a': 'test', 'b': ''})
    [{'a': 'test'}]
    >>> expand_vars_on_newlines({'a': '\n\n\n'})
    [{}]

    Filter variables (collapse to [] if filtered variables are empty):
    >>> expand_vars_on_newlines({'a': ''}, filter_variables=['a'])
    []
    >>> expand_vars_on_newlines({'a': 'test', 'b': ''}, filter_variables=['b'])
    []
    >>> expand_vars_on_newlines({'a': 'test', 'b': ''}, filter_variables=['a'])
    [{'a': 'test'}]
    >>> expand_vars_on_newlines({'a': '  \n  ', 'b': 'valid'}, filter_variables=['a'])
    []

    Real-world example:
    >>> expand_vars_on_newlines({'PATH': '/bin\n/usr/bin', 'HOME': '/root'})
    [{'PATH': '/bin', 'HOME': '/root'}, {'PATH': '/usr/bin', 'HOME': '/root'}]
    '''
    if filter_variables is None:
        filter_variables = []

    # Split values on newlines and create lists, filtering out empty/whitespace entries
    split_vars = {}
    for k, v in env_vars.items():
        if isinstance(v, str):
            values = [val.strip() for val in v.split('\n') if val.strip()]
        else:
            values = [str(v).strip()] if str(v).strip() else []

        # If this variable is in filter_variables and has no valid values, return empty list
        if k in filter_variables and not values:
            return []

        # Only include variables that have valid values
        if values:
            split_vars[k] = values

    # Generate all combinations
    from itertools import product
    keys = list(split_vars.keys())
    if not keys:
        return [{}]

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


################################################################################

def match_pattern_withvars(patterns, input_str, vars_dict=None):
    '''
    This function is similar to match_pattern in that it finds the pattern within patterns that input_str matches.
    It differs, however, in that it also accepts a vars_dict.
    The function will return a modified version of vars_dict with "transitive assignments" overwritten.
    For example, if we have that NAME gets assigned to $DEP after doing the pattern match,
    then we delete DEP from vars_dict and assign DEP's value to NAME.

    Simple examples:

        >>> patterns = ['recursive/$TEST/$NAME', 'simple/$TEST/$NAME', 'nonrecursive/$TEST/$NAME']
        >>> match_pattern_withvars(patterns, 'recursive/$TEST/$DEP', {'TEST': 'forward.json', 'NAME': 'c', 'DEP': 'b'})
        ('recursive/$TEST/$NAME', {'NAME': 'b', 'TEST': 'forward.json'})

        >>> match_pattern_withvars(patterns, 'recursive/$DEP1/$DEP2', {'NAME': 'f', 'DEP1': 'b', 'DEP2': 'c'})
        ('recursive/$TEST/$NAME', {'TEST': 'b', 'NAME': 'c'})

        >>> match_pattern_withvars(patterns, 'recursive/$DEP1/$DEP2', {'NAME': 'f', 'DEP1': 'b', 'DEP2': 'c', 'FOO': 'A'})
        ('recursive/$TEST/$NAME', {'TEST': 'b', 'NAME': 'c', 'FOO': 'A'})


    If no pattern matches, return None as the first argument.

        >>> match_pattern_withvars(patterns, 'jsons/$TEST', {'TEST': 'forward.json', 'NAME': 'c'})
        (None, {'TEST': 'forward.json', 'NAME': 'c'})

    If a pattern matches, but the variable is not found in vars_dict:

        >>> patterns=['outline.json', 'sub$LEVEL1/outline.json', 'sub$LEVEL1/sub$LEVEL2/outline.json', 'final.txt', 'sub$LEVEL1/summary_NOVAR.md', 'sub$LEVEL1/summary_SAMEVAR.md', 'sub$LEVEL1/summary_VARSUBSET.md', 'sub$LEVEL1/summary_FOO.md', 'sub$LEVEL1/summary_DEP.md', 'deps/$DEP', 'sub$LEVEL1/summary_EMPTY.md']
        >>> match_pattern_withvars(patterns, 'deps/a', {})
        ('deps/$DEP', {'DEP': 'a'})
    '''
    vars_dict1 = {}
    target1, target1_vars =  match_pattern(patterns, input_str)
    badvars = []
    for var, val in target1_vars.items():
        if val[0] == '$':
            if val[1:] in vars_dict:
                vars_dict1[var] = vars_dict[val[1:]]
                badvars.append(val[1:])
            else:
                raise ValueError
        elif var in vars_dict:
            vars_dict1[var] = vars_dict[var]
        else:
            vars_dict1[var] = val
    for var in vars_dict:
        if var not in vars_dict1 and var not in badvars:
            vars_dict1[var] = vars_dict[var]
    return (target1, vars_dict1)


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

    if '**' in input_string:
        raise ValueError(f"wildcard ** not allowed in input string")

    matches = match_pattern_starstar(patterns, input_string)
    if len(matches) == 0:
        return (None, {})
    elif len(matches) > 1:
        raise ValueError(f"Ambiguous pattern match for '{input_string}'")
    return matches[0]


def match_pattern_starstar(patterns, input_string):
    """
    Match an input string (containing **) against patterns and extract variables.

    ** in input_string can match any number of path segments in patterns.
    Variables matched by ** are not extracted (similar to how $VAR in input_string are not extracted).

    Args:
        patterns: List of pattern strings with variables like "$SERIES/$STORY/outline.json"
        input_string: String that may contain ** wildcards, e.g. "a/**/outline.json"

    Returns:
        List of tuples: [(matched_pattern, extracted_variables), ...]
        Empty list if no matches. Variables consumed by ** are not included in extracted_variables.

    Examples:

        >>> match_pattern_starstar(["$SERIES/$STORY/outline.json"], "mystory/**/outline.json")
        [('$SERIES/$STORY/outline.json', {'SERIES': 'mystory'})]
        >>> match_pattern_starstar(["$SERIES/$PART/$CHAPTER/outline.json"], "mystory/**/outline.json")
        [('$SERIES/$PART/$CHAPTER/outline.json', {'SERIES': 'mystory'})]
        >>> match_pattern_starstar(["$SERIES/$STORY/outline.json"], "**/outline.json")
        [('$SERIES/$STORY/outline.json', {})]
        >>> match_pattern_starstar(["$SERIES/$STORY/outline.json"], "mystory/**")
        [('$SERIES/$STORY/outline.json', {'SERIES': 'mystory'})]
        >>> match_pattern_starstar(["$A/$B/$C/file.json"], "start/**/file.json")
        [('$A/$B/$C/file.json', {'A': 'start'})]

    Multiple patterns:

        >>> match_pattern_starstar(["$A/$B/file.json", "$X/$Y/$Z/file.json"], "test/**/file.json")
        [('$A/$B/file.json', {'A': 'test'}), ('$X/$Y/$Z/file.json', {'X': 'test'})]
        >>> match_pattern_starstar(["$A/$B/file.json", "$X/$Y/file.json"], "test/**/file.json")
        [('$A/$B/file.json', {'A': 'test'}), ('$X/$Y/file.json', {'X': 'test'})]
        >>> match_pattern_starstar(["$A/specific/file.json", "$X/$Y/$Z/file.json"], "test/**/file.json")
        [('$A/specific/file.json', {'A': 'test'}), ('$X/$Y/$Z/file.json', {'X': 'test'})]
        >>> match_pattern_starstar(["$A/$B/config.json", "$X/$Y/$Z/config.json", "$P/$Q/$R/$S/config.json"], "proj/**/config.json")
        [('$A/$B/config.json', {'A': 'proj'}), ('$X/$Y/$Z/config.json', {'X': 'proj'}), ('$P/$Q/$R/$S/config.json', {'P': 'proj'})]
        >>> match_pattern_starstar(["$A/$B/outline.json", "$X/$Y/summary.json"], "proj/**/outline.json")
        [('$A/$B/outline.json', {'A': 'proj'})]
        >>> match_pattern_starstar(["$A/chapter/$B/file.json", "$X/$Y/$Z/file.json"], "book/**/file.json")
        [('$A/chapter/$B/file.json', {'A': 'book'}), ('$X/$Y/$Z/file.json', {'X': 'book'})]
        >>> match_pattern_starstar(["$A/$B/file.json", "$X/exact/file.json"], "test/exact/file.json")
        [('$A/$B/file.json', {'A': 'test', 'B': 'exact'}), ('$X/exact/file.json', {'X': 'test'})]

    If a variable matches with another variable with the "incorrect name", we include it in the output:

        >>> match_pattern_starstar(["$A/$B/file.json", "$X/$Y/$Z/file.json"], "test/$VAR/file.json")
        [('$A/$B/file.json', {'A': 'test', 'B': '$VAR'})]

    No match cases:

        >>> match_pattern_starstar(["$SERIES/$STORY/outline.json"], "mystory/**/summary.json")
        []
        >>> match_pattern_starstar(["$A/$B/file.json"], "first/file.json")
        []
        >>> match_pattern_starstar([], "test/**/file.json")
        []
        >>> match_pattern_starstar(['about.md', 'art.md', 'writing.md', 'characters/$CHARACTER/about.json', 'characters/$CHARACTER/artist_instructions.md', 'characters/$CHARACTER/character_sheet.png', 'locations/$LOCATION/about.json', 'locations/$LOCATION/reference.png', 'books/$LEVEL/themes.md', 'books/$LEVEL/$BOOK/content.jsonl', 'books/$LEVEL/$BOOK/frames/$FRAME_ID/art.json', 'books/$LEVEL/$BOOK/frames/$FRAME_ID/art.png', 'books/$LEVEL/$BOOK/frames/$FRAME_ID/page.pdf', 'books/$LEVEL/$BOOK/pages.pdf', 'books/$LEVEL/$BOOK/description.json'], 'locations/familyhouse_interior_diningroom/reference.json')
        []

    Real world examples:

        >>> match_pattern_starstar(["$PROJ/$MOD/src/$FILE.py", "$PROJ/tests/$TEST.py", "$PROJ/$DIR/$SUBDIR/config.json"], "myproj/**/config.json")
        [('$PROJ/$DIR/$SUBDIR/config.json', {'PROJ': 'myproj'})]
        >>> match_pattern_starstar(["$ORG/$REPO/src/main/$MODULE.rs", "$ORG/$REPO/target/debug/$BINARY", "$ORG/$REPO/docs/$SECTION/$PAGE.md", "$PROJECT/build/$ARTIFACT.jar"], "acme/widget/**/UserGuide.md")
        [('$ORG/$REPO/target/debug/$BINARY', {'ORG': 'acme', 'REPO': 'widget', 'BINARY': 'UserGuide.md'}), ('$ORG/$REPO/docs/$SECTION/$PAGE.md', {'ORG': 'acme', 'REPO': 'widget', 'PAGE': 'UserGuide'})]
        >>> match_pattern_starstar(["$APP/static/css/$THEME/$STYLE.css", "$APP/templates/$SECTION/$TEMPLATE.html", "$APP/api/v$VERSION/$ENDPOINT.py", "$APP/$MODULE/$COMPONENT/views.py"], "webapp/**/main.css")
        [('$APP/static/css/$THEME/$STYLE.css', {'APP': 'webapp', 'STYLE': 'main'})]
        >>> match_pattern_starstar(["services/$SERVICE/src/$MODULE.go", "services/$SERVICE/config/$ENV.yaml", "libs/$LIBRARY/$VERSION/src/$FILE.ts", "$ROOT/tools/$TOOL/bin/$EXECUTABLE"], "services/**/production.yaml")
        [('services/$SERVICE/config/$ENV.yaml', {'ENV': 'production'}), ('$ROOT/tools/$TOOL/bin/$EXECUTABLE', {'ROOT': 'services', 'EXECUTABLE': 'production.yaml'})]
        >>> match_pattern_starstar(["docs/$LANG/api/$MODULE/$CLASS.md", "docs/$LANG/guides/$CATEGORY/$GUIDE.md", "docs/assets/images/$SECTION/$IMAGE.png", "$PROJECT/wiki/$TOPIC.md"], "docs/**/Authentication.md")
        [('docs/$LANG/api/$MODULE/$CLASS.md', {'CLASS': 'Authentication'}), ('docs/$LANG/guides/$CATEGORY/$GUIDE.md', {'GUIDE': 'Authentication'}), ('$PROJECT/wiki/$TOPIC.md', {'PROJECT': 'docs', 'TOPIC': 'Authentication'})]
        >>> match_pattern_starstar(["build/$TARGET/$ARCH/lib$LIB.so", "build/$TARGET/bin/$BINARY", "dist/$PLATFORM/$VERSION/$PACKAGE.tar.gz", "cache/$HASH/$TEMP.tmp"], "build/**/myapp")
        [('build/$TARGET/bin/$BINARY', {'BINARY': 'myapp'})]
        >>> match_pattern_starstar(["$ENV/config/$SERVICE.conf", "global/config/$SETTING.ini", "$PROJECT/$MODULE/config/local.json", "deploy/$STAGE/$REGION/settings.yaml"], "prod/**/local.json")
        [('$PROJECT/$MODULE/config/local.json', {'PROJECT': 'prod'})]
        >>> match_pattern_starstar(["media/$TYPE/$YEAR/$MONTH/$FILE.$EXT", "assets/images/$CATEGORY/$SIZE/$IMAGE.jpg", "content/$SECTION/gallery/$ALBUM/$PHOTO.png"], "media/**/vacation.jpg")
        [('media/$TYPE/$YEAR/$MONTH/$FILE.$EXT', {'FILE': 'vacation', 'EXT': 'jpg'})]

    If a different variable name has been used in the pattern/input_string, we should still match:

        >>> match_pattern_starstar(['recursive/$TEST/$NAME', 'simple/$TEST/$NAME', 'nonrecursive/$TEST/$NAME'], 'recursive/$TEST/$DEP')
        [('recursive/$TEST/$NAME', {'NAME': '$DEP'})]
    """
    # Check for multiple ** in input_string
    if input_string.count('**') > 1:
        raise ValueError("Multiple ** wildcards are not supported in input_string")

    # Normalize input
    norm_input = re.sub(r'(\.\/)+', '', input_string)
    
    input_segments = norm_input.split('/')
    matches = []
    
    for pattern in patterns:
        # Normalize pattern
        norm_pattern = re.sub(r'(\.\/)+', '', pattern)
        pattern_segments = norm_pattern.split('/')
        
        # Try to match this pattern
        result = _match_pattern_with_starstar(pattern_segments, input_segments)
        if result is not None:
            matches.append((norm_pattern, result))
    
    return matches


def _match_pattern_with_starstar(pattern_segments, input_segments):
    """Helper to match pattern against input containing **."""
    
    # ** must match at least one segment, so input can't be longer than pattern
    num_stars = input_segments.count('**')
    non_star_segments = len(input_segments) - num_stars
    
    if len(pattern_segments) < non_star_segments + num_stars:
        return None
    
    variables = {}
    p_idx = 0  # pattern index  
    i_idx = 0  # input index
    
    while i_idx < len(input_segments):
        input_seg = input_segments[i_idx]
        
        if input_seg == '**':
            # ** consumes pattern segments until we find the next matching input segment
            if i_idx == len(input_segments) - 1:
                # ** at end, consume all remaining pattern segments
                p_idx = len(pattern_segments)
                i_idx += 1
            else:
                # Find next non-** input segment
                next_i_idx = i_idx + 1
                while next_i_idx < len(input_segments) and input_segments[next_i_idx] == '**':
                    next_i_idx += 1
                
                if next_i_idx >= len(input_segments):
                    # Rest of input is **, consume all remaining pattern segments
                    p_idx = len(pattern_segments)
                    i_idx = len(input_segments)
                else:
                    next_input_seg = input_segments[next_i_idx]
                    
                    # Calculate how many pattern segments we need to leave for remaining input
                    remaining_input_segments = len(input_segments) - next_i_idx
                    remaining_stars = sum(1 for seg in input_segments[next_i_idx:] if seg == '**')
                    min_pattern_segments_needed = remaining_input_segments - remaining_stars + remaining_stars
                    
                    # Find the rightmost pattern segment that could match next_input_seg
                    # while leaving enough segments for the rest of the input
                    found_match = False
                    max_p_idx = len(pattern_segments) - min_pattern_segments_needed
                    
                    for try_p_idx in range(p_idx, max_p_idx + 1):
                        if try_p_idx < len(pattern_segments):
                            try_pattern_seg = pattern_segments[try_p_idx]
                            if _segment_can_match(try_pattern_seg, next_input_seg):
                                # Check if we can match the rest of the input from this position
                                temp_vars = _try_match_from_position(
                                    pattern_segments[try_p_idx:], 
                                    input_segments[next_i_idx:]
                                )
                                if temp_vars is not None:
                                    # ** consumes segments from p_idx to try_p_idx (exclusive)
                                    p_idx = try_p_idx
                                    i_idx = next_i_idx
                                    found_match = True
                                    break
                    
                    if not found_match:
                        return None
        else:
            # Regular segment matching
            if p_idx >= len(pattern_segments):
                return None
                
            pattern_seg = pattern_segments[p_idx]
            match_result = _match_single_segment(pattern_seg, input_seg)
            if match_result is None:
                return None
            variables.update(match_result)
            p_idx += 1
            i_idx += 1
    
    # Check if we consumed all pattern segments
    if p_idx != len(pattern_segments):
        return None
        
    return variables

def _try_match_from_position(pattern_segments, input_segments):
    """Try to match remaining pattern and input segments."""
    temp_vars = {}
    p_idx = 0
    i_idx = 0
    
    while i_idx < len(input_segments) and p_idx < len(pattern_segments):
        input_seg = input_segments[i_idx]
        
        if input_seg == '**':
            # Skip ahead in pattern - simplified logic for validation
            segments_to_skip = 1
            if i_idx == len(input_segments) - 1:
                segments_to_skip = len(pattern_segments) - p_idx
            p_idx += segments_to_skip
            i_idx += 1
        else:
            pattern_seg = pattern_segments[p_idx]
            match_result = _match_single_segment(pattern_seg, input_seg)
            if match_result is None:
                return None
            temp_vars.update(match_result)
            p_idx += 1
            i_idx += 1
    
    if p_idx == len(pattern_segments) and i_idx == len(input_segments):
        return temp_vars
    return None

def _segment_can_match(pattern_seg, input_seg):
    """Check if a pattern segment could match an input segment."""
    return _match_single_segment(pattern_seg, input_seg) is not None

def _match_single_segment(pattern_seg, input_seg):
    """Match a single pattern segment against input segment."""
    import re
    
    if '$' not in pattern_seg:
        return {} if pattern_seg == input_seg else None
    
    # Handle variables in pattern segment
    regex = '^'
    pos = 0
    var_names = []
    
    while pos < len(pattern_seg):
        if pattern_seg[pos] == '$':
            var_start = pos + 1
            var_end = var_start
            while var_end < len(pattern_seg) and (pattern_seg[var_end].isalnum() or pattern_seg[var_end] == '_'):
                var_end += 1
            
            var_name = pattern_seg[var_start:var_end]
            var_placeholder = f"${var_name}"
            
            if var_placeholder in input_seg:
                regex += re.escape(var_placeholder)
            else:
                var_names.append(var_name)
                regex += '(.*?)'
            
            pos = var_end
        else:
            if pattern_seg[pos] in '.^$*+?{}[]\\|()':
                regex += '\\'
            regex += pattern_seg[pos]
            pos += 1
    
    regex += '$'
    match = re.match(regex, input_seg)
    
    if not match:
        return None
    
    variables = {}
    for j, var_name in enumerate(var_names):
        variables[var_name] = match.group(j + 1)
    
    return variables


def reorder_variable_dictionary(var_dict):
    """
    Reorders a dictionary of shell variables to respect dependencies.
    We expect that var_dict has keys that represent shell variable names,
    and the values are commands that are run to set the value of those variables.
    Some of the commands may reference other variables in the dictionary,
    and we reorder the dictionary so that if the commands are run (in the order of the dictionary) there will be no error.
    That is, if VAR2 depends on VAR1, then VAR2 will appear after VAR1 in the dictionary.

    Raises:
        ValueError: If circular dependencies are detected

    >>> # Simple dependency chain
    >>> d1 = {'C': 'echo $B', 'B': 'echo $A', 'A': 'echo hello'}
    >>> result1 = reorder_variable_dictionary(d1)
    >>> list(result1.keys())
    ['A', 'B', 'C']

    >>> # No dependencies
    >>> d2 = {'X': 'echo x', 'Y': 'echo y', 'Z': 'echo z'}
    >>> result2 = reorder_variable_dictionary(d2)
    >>> set(result2.keys()) == {'X', 'Y', 'Z'}
    True

    >>> # Complex dependencies with ${} syntax
    >>> d3 = {'PATH': 'echo ${HOME}/bin:$OLDPATH', 'HOME': 'echo /home/user', 'OLDPATH': 'echo $PATH_BACKUP', 'PATH_BACKUP': 'echo /usr/bin'}
    >>> result3 = reorder_variable_dictionary(d3)
    >>> keys = list(result3.keys())
    >>> keys.index('PATH_BACKUP') < keys.index('OLDPATH')
    True
    >>> keys.index('HOME') < keys.index('PATH')
    True

    >>> # Direct circular dependency
    >>> d4 = {'VAR1': 'echo $VAR1'}
    >>> reorder_variable_dictionary(d4)
    Traceback (most recent call last):
    ...
    ValueError: Circular dependencies detected: VAR1

    >>> # Indirect circular dependency
    >>> d5 = {'VAR1': 'echo $VAR2', 'VAR2': 'echo $VAR1'}
    >>> reorder_variable_dictionary(d5)
    Traceback (most recent call last):
    ...
    ValueError: Circular dependencies detected: VAR1, VAR2

    >>> # 4-variable circular dependency: A->B->C->D->A
    >>> d6 = {'A': 'echo $D', 'B': 'echo $A', 'C': 'echo $B', 'D': 'echo $C'}
    >>> reorder_variable_dictionary(d6)
    Traceback (most recent call last):
    ...
    ValueError: Circular dependencies detected: A, B, C, D
    """
    # Build dependency graph
    dependencies = defaultdict(set)

    for var, command in var_dict.items():
        # Find variable references like $VAR or ${VAR}
        refs = re.findall(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?', command)
        for ref in refs:
            if ref in var_dict:
                if ref == var:
                    raise ValueError(f"Circular dependencies detected: {var}")
                dependencies[var].add(ref)

    # Topological sort using Kahn's algorithm
    in_degree = {var: 0 for var in var_dict}
    for var in dependencies:
        for dep in dependencies[var]:
            in_degree[var] += 1

    queue = deque([var for var in in_degree if in_degree[var] == 0])
    result = []

    while queue:
        var = queue.popleft()
        result.append(var)
        for dependent in var_dict:
            if var in dependencies[dependent]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

    # Check for circular dependencies
    if len(result) != len(var_dict):
        remaining = sorted(set(var_dict.keys()) - set(result))
        raise ValueError(f"Circular dependencies detected: {', '.join(remaining)}")

    return {var: var_dict[var] for var in result}
