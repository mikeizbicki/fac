'''
FIXME:
This code should probably be unified with the template code.
'''
import re
import subprocess
from fac.Errors import FACError
from fac.Logging import logger
from fac.util.targets import match_pattern_starstar


def eval_var(expr, env, var='<unknown>', target='<unknown>', targets_dict={}):
    '''
    Evaluate the bash expression expr with the given environment variables.

    >>> eval_var('echo "hello $NAME"', {'NAME': 'world'})
    'hello world'

    If the bash command has non-zero exit code, we raise an error.

    >>> eval_var('ls /nonexistent/path', {})
    Traceback (most recent call last):
        ...
    VariableEvaluationError

    The var and target parameters are only used for better error messages in the log.
    '''
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
