class FacJSON:
    """
    A JSON-backed dictionary-like class that persists data to disk.
    Used for storing settings for targets.

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

