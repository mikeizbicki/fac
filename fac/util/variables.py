'''
FIXME:
This code should probably be unified with the template code.
'''
import re
import subprocess
import glob
import json
import os

import jq as jqlib

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
        logger.error({'env': dict(env)}, submessage=True)
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
    # Use shlex to properly parse shell arguments (handles quotes)
    import shlex
    try:
        parts = shlex.split(expr)
    except ValueError:
        return None
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

    >>> _ls_shortcut(['/nonexistent/path/xyz'])  # doctest: +ELLIPSIS
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


def _jq_shortcut(args, data=None):
    r'''
    Execute jq command in Python using the jq library.
    Supports: jq [-r] jq_expr path

    Returns stdout as a string, or None if format not supported.
    Raises an exception if file doesn't exist or JSON is invalid.

    The data parameter is for testing only: when provided, it should be the
    raw JSON string and the file path argument is ignored.

    Basic field access:

    >>> _jq_shortcut(['.name', '_'], data='{"name": "alice", "age": 30}')
    '"alice"'

    With -r flag (raw output):

    >>> _jq_shortcut(['-r', '.name', '_'], data='{"name": "alice"}')
    'alice'

    -r flag can appear after expression:

    >>> _jq_shortcut(['.name', '-r', '_'], data='{"name": "bob"}')
    'bob'

    Array iteration with .[]:

    >>> _jq_shortcut(['.[]', '_'], data='[1, 2, 3]')
    '1\n2\n3'

    Nested field access:

    >>> _jq_shortcut(['-r', '.user.name', '_'], data='{"user": {"name": "charlie"}}')
    'charlie'

    Array index access:

    >>> _jq_shortcut(['-r', '.[1]', '_'], data='["a", "b", "c"]')
    'b'

    Identity expression:

    >>> import json
    >>> result = _jq_shortcut(['.', '_'], data='{"x": 1}')
    >>> json.loads(result) == {"x": 1}
    True

    Keys expression:

    >>> _jq_shortcut(['-r', 'keys[]', '_'], data='{"b": 1, "a": 2}')
    'a\nb'

    Chained operations with array iteration:

    >>> _jq_shortcut(['-r', '.[].name', '_'], data='[{"name": "x"}, {"name": "y"}]')
    'x\ny'

    File not found raises error:

    >>> _jq_shortcut(['.', '/nonexistent/file.json'])  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    FileNotFoundError: ...

    Complex expressions work with the jq library:

    >>> _jq_shortcut(['-r', '[.[] | select(.x > 2)] | length', '_'], data='[{"x": 5}, {"x": 1}, {"x": 10}]')
    '2'

    Handles null values:

    >>> _jq_shortcut(['.name', '_'], data='{"name": null}')
    'null'

    Handles boolean values:

    >>> _jq_shortcut(['.flag', '_'], data='{"flag": true}')
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

    # If data is provided (for testing), use it directly
    if data is not None:
        data = json.loads(data)
    else:
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        with open(path, 'r') as f:
            data = json.load(f)

    # Use the jq library to evaluate the expression
    try:
        compiled = jqlib.compile(expr)
        results = list(compiled.input(data).all())
    except Exception:
        # If jq compilation or execution fails, return None to fall back to subprocess
        return None

    output_lines = []
    for result in results:
        if raw_output and isinstance(result, str):
            output_lines.append(result)
        else:
            output_lines.append(json.dumps(result))

    return '\n'.join(output_lines)
