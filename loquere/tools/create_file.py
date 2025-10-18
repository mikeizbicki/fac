import pathlib
import os

from loquere.utils import tool_print

def tool(path, content, makedirs=True):
    '''
    >>> create_file('/test', 'test')
    Traceback (most recent call last):
    ...
    ValueError: Path is not relative to pwd
    '''

    tool_print(f'create_file({path}, content=...)')

    # SECURITY:
    # ensure that the path does not access an ancestor of the current folder
    path = pathlib.Path(os.path.abspath(path))
    pwd = os.getcwd()
    if not path.is_relative_to(pwd):
        raise ValueError('Path is not relative to pwd')

    # make needed directories if they don't exist
    if makedirs:
        dirname = os.path.dirname(path)
        os.makedirs(dirname, exist_ok=True)

    # create the file
    with open(path, 'x') as fout:
        fout.write(content)

data = {
    "type": "function",
    "function": {
        "name": "create_file",
        "description": "Create a file with the specified content. This function will fail if the file already exists (in that case, the `overwrite_file` function should be used).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A filename or relative path for where the file will be created.  Absolute paths are not allowed, and the `..` parent special file is also not allowed.",
                },
                "content": {
                    "type": "string",
                    "description": "The content of the created file."
                }
            },
            "required": ["path", "content"],
        },
    },
}
