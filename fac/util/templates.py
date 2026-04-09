'''
This file contains utility functions for working with templates.
A template is a string that contains arbitrary bash variables and subshells;
we will invoke a bash subshell to actually process these templates and convert them into text.
'''

import os
import re
import subprocess
import tempfile


def process_template(template_content, env_vars=None, print_function=None, template_name=None):
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
            # The shell script wraps the template_content inside a heredoc
            # and adds set -eu to help prevent errors
            script_content = f'''
#!/bin/bash
set -e
set -u
cat << __EOF_DELIMITER_END__
{template_content}
__EOF_DELIMITER_END__
'''.strip()
            script.write(script_content)

        # Make the script executable
        os.chmod(script_path, 0o755)

        # Execute the script and capture output
        result = subprocess.run([script_path], capture_output=True, text=True, env={**os.environ, **env_vars})
        if result.returncode != 0 or len(result.stderr.strip()) > 0:
            error = TemplateProcessingError(
                result.returncode,
                result.stdout,
                result.stderr,
                env_vars,
                script_content,
                )
            if print_function and template_name:
                print_function(f'error processing template {template_name}: {error.get_bash_error()}')
                error.print_template(print_function=print_function)
                print_function('bound variables:', submessage=True)
                for var in env_vars:
                    print_function(f' - {var}: {repr(env_vars[var])}', submessage=True)
            raise error
        return result.stdout.strip()

    finally:
        # Ensure the temporary file is removed
        if os.path.exists(script_path):
            os.unlink(script_path)


class TemplateProcessingError(Exception):
    """Exception raised when template processing fails."""

    def __init__(self, returncode, stdout, stderr, env_vars, script_content):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.env_vars = env_vars
        self.script_content = script_content
        super().__init__(stderr)

    def get_bash_error(self):

        # unbound variables
        pattern = r':\s*([^:]+)\s*:\s*unbound variable'
        match = re.search(pattern, self.stderr)
        if match:
            return f'unbound variable: {match.group(1).strip()}'

        # syntax errors
        if 'syntax' in self.stderr:
            return 'syntax error'

        # unknown
        return 'unknown error -- ' + self.stderr

    def print_template(self, print_function=print, window_size=20):
        pattern = r':\s*line\s+(\d+):'
        match = re.search(pattern, self.stderr)
        if match:
            print_function('template:', submessage=True)
            error_line_number = int(match.group(1))
            lines = self.script_content.split('\n')
            lines = lines[4:-1]  # MAGIC NUMBERS that extract the heredoc from the script
            start_line = max(0, error_line_number - window_size)
            stop_line = min(error_line_number + window_size, len(lines))
            num_digits = len(str(stop_line))
            for line_number in range(start_line, stop_line):
                if line_number == error_line_number - 3:  # MAGIC NUMBER that correctly adjusts line number FIXME: doesn't actually always work
                    pointer = '-->'
                else:
                    pointer = '   '
                print_function(f' {pointer} {line_number + 1:>{num_digits}}: {lines[line_number]}')
        else:
            print_function('bash error did not contain line number information :(', submessage=True)
