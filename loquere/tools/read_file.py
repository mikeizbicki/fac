import pathlib
import os

from loquere.utils import tool_print

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
        return fin.read()

data = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the contents of the specified file.  If you think you might need to read the contents of multiple files, multiple tool requests should be sent at the same time to speed up processing.",
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
