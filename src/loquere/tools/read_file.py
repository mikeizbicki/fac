import pathlib
import os

from loquere.utils import tool_print

enable = True

def tool(path):
    '''
    >>> read_file('/test', 'test')
    Traceback (most recent call last):
    ...
    ValueError: Path is not relative to pwd
    '''

    tool_print(f'read_file({path})')

    # SECURITY:
    # ensure that the path does not access an ancestor of the current folder
    path = pathlib.Path(os.path.abspath(path))
    pwd = os.getcwd()
    if not path.is_relative_to(pwd):
        raise ValueError('Path is not relative to pwd')

    # read the file
    with open(path, 'rt') as fin:
        try:
            return fin.read()
        except UnicodeDecodeError as e:
            return f'"{path}" is a binary file and cannot be loaded'

data = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the contents of the specified text file.  If you think you might need to read the contents of multiple files, multiple tool requests should be sent at the same time to speed up processing.  Never read files before using fac_build (if a file needs to be read, fac_build will read it automatically).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A filename or relative path that specifies the file to read.  Absolute paths are not allowed, and the `..` parent special file is also not allowed.",
                },
            },
            "required": ["path"],
        },
    },
}
