'''
This file contains utility functions that perform IO.
These functions are much more difficult to test properly than the pure functions in "fac/utils.py".
'''

# stdlib imports
import base64
import json
import mimetypes
import os

# external lib imports
import json_repair
import jsonschema

# project imports
from fac.Logging import *
from fac.Errors import *


def validate_file(path, schema_file=None, fix=False):
    '''
    Frontier LLMs are good at generating content that adheres to a schema,
    but even the best LLMs sometimes make mistakes.
    This function validates that a file is correctly formatted so that downstream tasks do not fail.
    Optionally it can repair certain types of common problems and reformat files so that they are more consistent and human readable.
    '''

    _, extension = os.path.splitext(path)

    # ensure the input path exists
    if not os.path.exists(path):
        logger.warning(f'path="{path}" does not exist, cannot validate', submessage=True)
        return False

    # ensure the file is non-empty
    elif not path.startswith('/dev/') and os.path.getsize(path) == 0:
        logger.warning(f'os.path.getsize("{path}")=0')

    # validate JSON files
    elif extension == '.json':

        # ensure that the JSON can be parsed
        with open(path) as fin:
            text = fin.read()
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f'JSONDecodeError: path={path} schema_file={schema_file}')
            if fix:
                logger.info(f'fixing JSONDecodeError in path={path}')
                with open(path, 'wt') as fout:
                    obj = json_repair.loads(text, skip_json_loads=True)
                    json.dump(obj, fout)
            else:
                raise e

        # verify that the JSON matches the schema
        if schema_file:
            with open(path) as fin:
                data = json.load(fin)
            try:
                with open(schema_file) as fin:
                    schema = json.load(fin)
                    jsonschema.validate(instance=data, schema=schema)
            except jsonschema.exceptions.ValidationError as e:
                log_message = str(e).split('\n')[0]
                logger.warning(f'{path}: JSON schema validation error: {log_message}')

        # reformat with pretty indentation
        if fix:
            logger.info('fixing JSON indentation')
            with open(path, 'r') as fin:
                data = json.load(fin)
            with open(path, 'w', encoding='utf-8') as fout:
                json.dump(data, fout, indent=4, ensure_ascii=False)

    # fix markdown files
    elif fix and extension in ['.md' or '.markdown']:
        logger.info(f'fixing markdown formatting in path={path}')
        with open(path, "r+") as fout:
            markdown_text = fout.read()
            formatted_text = mdformat.text(markdown_text)
            fout.seek(0)
            fout.write(formatted_text)
            fout.truncate()

    # no errors, return True
    return True


def binary_file_to_base64_url(file_path):
    '''
    A common way to pass binary files to LLMs is via base64 encoded urls.
    This function converts a local image into this format.
    '''
    try:
        with open(file_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            mime_type = mimetypes.guess_type(file_path)[0] or 'image/png'
            return f"data:{mime_type};base64,{encoded_string}"
    except FileNotFoundError:
        logger.error(f'file not found: {file_path}')
        raise FACError


class FacJSON:
    """
    A JSON-backed dictionary-like class that persists data to disk.
    Used for storing settings for targets.

    NOTE:
    This implementation is not currently thread-safe.

    >>> # tests need to create a temporary file
    >>> import tempfile, os
    >>> with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
    ...     temp_path = f.name
    >>>
    >>> # test getting/setting
    >>> fac = FacJSON(temp_path)
    >>> fac.set('name', 'John')
    >>> fac.get('name')
    'John'
    >>> fac.set('age', 30)
    >>> fac.get('age', 0)
    30
    >>> fac.get('missing', 'default')
    'default'
    >>>
    >>> # test persistence
    >>> fac2 = FacJSON(temp_path)
    >>> fac2.get('name')
    'John'
    >>> fac2.get('age')
    30
    >>> # cleanup tests
    >>> os.unlink(temp_path)
    """
    def __init__(self, path):
        self._path = path
        self._fac_path = self.convert_path(path)
        try:
            with open(self._fac_path) as fin:
                self._data = json.load(fin)
        except FileNotFoundError:
            self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def save(self):
        """Save the current dict contents to disk."""
        with open(self._fac_path, 'w') as fout:
            json.dump(self._data, fout)

    @staticmethod
    def convert_path(path):
        """
        Prefix the filename with '.' and suffix with '.facjson'.

        >>> FacJSON.convert_path("/home/user/document.txt")
        '/home/user/.document.txt.facjson'
        >>> FacJSON.convert_path("document.txt")
        '.document.txt.facjson'
        >>> FacJSON.convert_path("/path/to/file")
        '/path/to/.file.facjson'
        """
        directory = os.path.dirname(path)
        filename = os.path.basename(path)
        new_filename = f".{filename}.facjson"
        return os.path.join(directory, new_filename)
