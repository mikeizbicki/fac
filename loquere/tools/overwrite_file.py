import pathlib
import os

from loquere.utils import tool_print

def tool(path, content):
    '''
    >>> overwrite_file('/test', 'test')
    Traceback (most recent call last):
    ...
    ValueError: Path is not relative to pwd
    '''

    tool_print(f'overwrite_file({path}, content=...)')

    # SECURITY:
    # ensure that the path does not access an ancestor of the current folder
    path = pathlib.Path(os.path.abspath(path))
    pwd = os.getcwd()
    if not path.is_relative_to(pwd):
        raise ValueError('Path is not relative to pwd')

    # ensure the file exists
    with open(path, 'r') as fin:
        pass

    # update the file
    with open(path, 'w') as fout:
        fout.write(content)

data = {
    "type": "function",
    "function": {
        "name": "overwrite_file",
        "description": "Overwrites the content in an existing file and adds new content.  This function should be used whenever the user asks to modify an existing file.  You must have explicitly read the contents of the file before using this function.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A filename or relative path.  Absolute paths are not allowed, and the `..` parent special file is also not allowed.",
                },
                "content": {
                    "type": "string",
                    "description": "The new content of the file."
                }
            },
            "required": ["path", "content"],
        },
    },
}

