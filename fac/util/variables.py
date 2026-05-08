'''
FIXME:
This code should probably be unified with the template code.
'''
import re
import subprocess
import glob
import json
import os

from fac.Errors import FACError
from fac.Logging import logger
from fac.util.targets import match_pattern_starstar, substitute_variables


def eval_var(expr, env, var='<unknown>', target='<unknown>', targets_dict={}, use_shortcuts=True):
    '''
    Evaluate the bash expression expr with the given environment variables.

    >>> eval_var('echo "hello $NAME"', {'NAME': 'world'})
    'hello world'

    If the bash command has non-zero exit code, we raise an error.

    >>> eval_var('ls /nonexistent/path', {})  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    variables.VariableEvaluationError

    The var and target parameters are only used for better error messages in the log.

    When use_shortcuts=True, simple ls and jq commands are executed in Python
    for performance. Results should be identical:

    >>> import tempfile, os
    >>> with tempfile.TemporaryDirectory() as d:
    ...     open(os.path.join(d, 'a.txt'), 'w').close()
    ...     open(os.path.join(d, 'b.txt'), 'w').close()
    ...     r1 = eval_var(f'ls {d}', {}, use_shortcuts=True)
    ...     r2 = eval_var(f'ls {d}', {}, use_shortcuts=False)
    ...     r1 == r2
    True

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{"name": "alice", "age": 30}')
    ...     r1 = eval_var(f'jq -r .name {p}', {}, use_shortcuts=True)
    ...     r2 = eval_var(f'jq -r .name {p}', {}, use_shortcuts=False)
    ...     r1 == r2
    True

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('[1, 2, 3]')
    ...     r1 = eval_var(f'jq ".[]" {p}', {}, use_shortcuts=True)
    ...     r2 = eval_var(f'jq ".[]" {p}', {}, use_shortcuts=False)
    ...     r1 == r2
    True

    Variable substitution works with shortcuts:

    >>> import tempfile, os
    >>> with tempfile.TemporaryDirectory() as d:
    ...     open(os.path.join(d, 'file.txt'), 'w').close()
    ...     r1 = eval_var('ls $DIR', {'DIR': d}, use_shortcuts=True)
    ...     r2 = eval_var('ls $DIR', {'DIR': d}, use_shortcuts=False)
    ...     r1 == r2
    True
    '''
    # Try Python shortcuts for common commands
    if use_shortcuts:
        # Substitute variables to get the actual command
        substituted = substitute_variables(expr.strip(), env)
        if len(substituted) == 1:
            expr1 = substituted[0]
            try:
                result = _try_shortcut(expr1)
                if result is not None:
                    return _format_result(result)
            except Exception:
                # Fall back to subprocess on any error
                pass

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
    stdout = cmd.stdout.strip()
    stderr = cmd.stderr.strip()

    # handle any errors
    if cmd.returncode != 0:
        logger.error(f'Error evaluating variable {var} in target {target}')

        # print hints for how to resolve common errors
        patterns = [
            r"jq: error: Could not open file (.+?):",
            r"ls: cannot access '(.+?)':",
        ]
        for pattern in patterns:
            match = re.search(pattern, cmd.stderr)
            if match:
                path = match.group(1)
                target_matches = match_pattern_starstar(targets_dict, path)
                logger.error(f'HINT: {var} depends on file {path}')
                if len(target_matches) == 0:
                    logger.error('HINT: there are no targets that correspond to this path')
                else:
                    logger.error(f'HINT: add "{target_matches[0][0]}" to the dependencies to build the file')

        # print raw output
        logger.error('stderr: |', submessage=True)
        for line in (stderr.strip()).strip().split('\n'):
            logger.error('  ' + line, submessage=True)
        if len(stdout) > 0:
            logger.error('stdout: |', submessage=True)
            for line in stdout.split('\n'):
                logger.error('  ' + line, submessage=True)
        #logger.error({'context': context.to_dict()}, submessage=True)
        raise VariableEvaluationError

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
    pass


def _format_result(stdout):
    '''
    Format the result of a command, zero-padding integers.
    This matches the formatting done in eval_var.
    '''
    lines = []
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            try:
                intval = int(line)
                line = f'{intval:04d}'
            except ValueError:
                pass
            lines.append(line)
    return '\n'.join(lines)


def _try_shortcut(expr):
    '''
    Try to execute a command using Python shortcuts.
    Returns the stdout string if successful, None if the command format is not supported.
    Raises an exception if the command fails (e.g., file not found).
    '''
    parts = expr.split()
    if not parts:
        return None

    cmd = parts[0]
    if cmd == 'ls':
        return _ls_shortcut(parts[1:])
    elif cmd == 'jq':
        return _jq_shortcut(parts[1:])
    return None


def _ls_shortcut(args):
    '''
    Execute ls command in Python.
    Supports: ls [-a] path1 [path2 ...]

    Returns stdout as a string, or None if format not supported.
    Raises FileNotFoundError if path doesn't exist.

    Basic usage:

    >>> import tempfile, os
    >>> with tempfile.TemporaryDirectory() as d:
    ...     open(os.path.join(d, 'a.txt'), 'w').close()
    ...     open(os.path.join(d, 'b.txt'), 'w').close()
    ...     result = _ls_shortcut([d])
    ...     sorted(result.strip().split('\\n'))
    ['a.txt', 'b.txt']

    Multiple paths:

    >>> import tempfile, os
    >>> with tempfile.TemporaryDirectory() as d:
    ...     d1 = os.path.join(d, 'dir1')
    ...     d2 = os.path.join(d, 'dir2')
    ...     os.makedirs(d1)
    ...     os.makedirs(d2)
    ...     open(os.path.join(d1, 'x.txt'), 'w').close()
    ...     open(os.path.join(d2, 'y.txt'), 'w').close()
    ...     result = _ls_shortcut([d1, d2])
    ...     'x.txt' in result and 'y.txt' in result
    True

    With -a flag (shows hidden files):

    >>> import tempfile, os
    >>> with tempfile.TemporaryDirectory() as d:
    ...     open(os.path.join(d, '.hidden'), 'w').close()
    ...     open(os.path.join(d, 'visible'), 'w').close()
    ...     result_no_a = _ls_shortcut([d])
    ...     result_with_a = _ls_shortcut(['-a', d])
    ...     '.hidden' not in result_no_a and '.hidden' in result_with_a
    True

    -a flag can appear anywhere:

    >>> import tempfile, os
    >>> with tempfile.TemporaryDirectory() as d:
    ...     open(os.path.join(d, '.hidden'), 'w').close()
    ...     result = _ls_shortcut([d, '-a'])
    ...     '.hidden' in result
    True

    File not found raises error:

    >>> _ls_shortcut(['/nonexistent/path/xyz'])
    Traceback (most recent call last):
        ...
    FileNotFoundError: ...

    Glob patterns:

    >>> import tempfile, os
    >>> with tempfile.TemporaryDirectory() as d:
    ...     open(os.path.join(d, 'a.txt'), 'w').close()
    ...     open(os.path.join(d, 'b.txt'), 'w').close()
    ...     open(os.path.join(d, 'c.json'), 'w').close()
    ...     result = _ls_shortcut([os.path.join(d, '*.txt')])
    ...     lines = sorted(result.strip().split('\\n'))
    ...     len(lines) == 2 and all('.txt' in l for l in lines)
    True
    '''
    show_all = False
    paths = []

    for arg in args:
        if arg == '-a':
            show_all = True
        elif arg.startswith('-'):
            # Unsupported flag
            return None
        else:
            paths.append(arg)

    if not paths:
        return None

    all_entries = []
    for path in paths:
        # Handle glob patterns
        if '*' in path or '?' in path or '[' in path:
            expanded = glob.glob(path)
            if not expanded:
                raise FileNotFoundError(f"No matches for pattern: {path}")
            for p in expanded:
                all_entries.append(os.path.basename(p))
        elif os.path.isdir(path):
            entries = os.listdir(path)
            if not show_all:
                entries = [e for e in entries if not e.startswith('.')]
            all_entries.extend(sorted(entries))
        elif os.path.exists(path):
            all_entries.append(os.path.basename(path))
        else:
            raise FileNotFoundError(f"Path not found: {path}")

    return '\n'.join(all_entries)


def _jq_shortcut(args):
    r'''
    Execute jq command in Python.
    Supports: jq [-r] jq_expr path

    Returns stdout as a string, or None if format not supported.
    Raises an exception if file doesn't exist or JSON is invalid.

    Basic field access:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{"name": "alice", "age": 30}')
    ...     _jq_shortcut(['.name', p])
    '"alice"'

    With -r flag (raw output):

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{"name": "alice"}')
    ...     _jq_shortcut(['-r', '.name', p])
    'alice'

    -r flag can appear after expression:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{"name": "bob"}')
    ...     _jq_shortcut(['.name', '-r', p])
    'bob'

    Array iteration with .[]:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('[1, 2, 3]')
    ...     _jq_shortcut(['.[]', p])
    '1\n2\n3'

    Nested field access:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{"user": {"name": "charlie"}}')
    ...     _jq_shortcut(['-r', '.user.name', p])
    'charlie'

    Array index access:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('["a", "b", "c"]')
    ...     _jq_shortcut(['-r', '.[1]', p])
    'b'

    Identity expression:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{"x": 1}')
    ...     result = _jq_shortcut(['.', p])
    ...     json.loads(result) == {"x": 1}
    True

    Keys expression:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{"b": 1, "a": 2}')
    ...     result = _jq_shortcut(['-r', 'keys[]', p])
    ...     sorted(result.split('\\n'))
    ['a', 'b']

    Chained operations with array iteration:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('[{"name": "x"}, {"name": "y"}]')
    ...     _jq_shortcut(['-r', '.[].name', p])
    'x\ny'

    File not found raises error:

    >>> _jq_shortcut(['.', '/nonexistent/file.json'])
    Traceback (most recent call last):
        ...
    FileNotFoundError: ...

    Unsupported expression returns None:

    >>> import tempfile, os
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{}')
    ...     _jq_shortcut(['select(.x > 1)', p]) is None
    True

    Handles null values:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{"name": null}')
    ...     _jq_shortcut(['.name', p])
    'null'

    Handles boolean values:

    >>> import tempfile, os, json
    >>> with tempfile.TemporaryDirectory() as d:
    ...     p = os.path.join(d, 'test.json')
    ...     _ = open(p, 'w').write('{"flag": true}')
    ...     _jq_shortcut(['.flag', p])
    'true'
    '''
    raw_output = False
    expr = None
    path = None

    for arg in args:
        if arg == '-r':
            raw_output = True
        elif arg.startswith('-'):
            # Unsupported flag
            return None
        elif expr is None:
            expr = arg
        elif path is None:
            path = arg
        else:
            # Too many arguments
            return None

    if expr is None or path is None:
        return None

    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, 'r') as f:
        data = json.load(f)

    results = _eval_jq_expr(expr, data)
    if results is None:
        return None

    output_lines = []
    for result in results:
        if raw_output and isinstance(result, str):
            output_lines.append(result)
        else:
            output_lines.append(json.dumps(result))

    return '\n'.join(output_lines)


def _eval_jq_expr(expr, data):
    '''
    Evaluate a simple jq expression on data.
    Returns a list of results, or None if expression is not supported.

    Supports:
    - . (identity)
    - .field, .field1.field2 (field access)
    - .[] (array/object iteration)
    - .[n] (array index)
    - keys, keys[] (object keys)
    - Combinations like .[].field, .field[]
    '''
    expr = expr.strip()

    # Handle keys and keys[]
    if expr == 'keys':
        if isinstance(data, dict):
            return [sorted(data.keys())]
        return None
    if expr == 'keys[]':
        if isinstance(data, dict):
            return sorted(data.keys())
        return None

    # Must start with .
    if not expr.startswith('.'):
        return None

    # Check for unsupported syntax
    unsupported = ['|', 'select', 'map', 'if', 'then', 'else', 'as', '@', '$', '+', '-', '*', '/', '==', '!=', '<', '>', 'and', 'or', 'not']
    for u in unsupported:
        if u in expr:
            return None

    return _eval_jq_path(expr[1:], [data])


def _eval_jq_path(path, values):
    '''
    Evaluate a jq path expression on a list of values.
    Returns a list of results.
    '''
    if not path:
        return values

    results = []
    for value in values:
        partial = _eval_jq_single_step(path, value)
        if partial is None:
            return None
        new_values, remaining_path = partial
        sub_results = _eval_jq_path(remaining_path, new_values)
        if sub_results is None:
            return None
        results.extend(sub_results)

    return results


def _eval_jq_single_step(path, value):
    '''
    Evaluate a single step of a jq path.
    Returns (list_of_values, remaining_path) or None if not supported.
    '''
    if not path:
        return ([value], '')

    # Handle .[] (iterate)
    if path.startswith('[]'):
        remaining = path[2:]
        if remaining.startswith('.'):
            remaining = remaining[1:]
        elif remaining and not remaining.startswith('['):
            return None

        if isinstance(value, list):
            return (value, remaining)
        elif isinstance(value, dict):
            return (list(value.values()), remaining)
        else:
            return None

    # Handle .[n] (array index)
    if path.startswith('['):
        end = path.find(']')
        if end == -1:
            return None
        index_str = path[1:end]
        remaining = path[end + 1:]
        if remaining.startswith('.'):
            remaining = remaining[1:]

        try:
            index = int(index_str)
            if isinstance(value, list) and -len(value) <= index < len(value):
                return ([value[index]], remaining)
            return None
        except ValueError:
            return None

    # Handle .field
    # Find end of field name
    end = 0
    while end < len(path) and path[end] not in '.[]':
        end += 1

    field = path[:end]
    remaining = path[end:]
    if remaining.startswith('.'):
        remaining = remaining[1:]

    if isinstance(value, dict) and field in value:
        return ([value[field]], remaining)
    elif isinstance(value, dict):
        # Field doesn't exist - return null like jq does
        return ([None], remaining)
    else:
        return None
