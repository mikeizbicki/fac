class FACError(Exception):
    def __init__(self, src=None):
        self.src = src

class DirtyRepo(FACError):
    pass

class CommandExecutionError(FACError):
    def __init__(self, returncode, stdout):
        errorstrs = [
            f"result.returncode={returncode}",
            f"result.output={stdout}",
            ]
        super().__init__('\n'.join(errorstrs))

