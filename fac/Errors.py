'''
Error types for fac.

Errors are split into two branches so the top-level handler can decide
whether to print a Python traceback:

- UserError: something is wrong with the user's fac.yaml, a template,
  a script, an LLM response, or the environment (e.g. git dirty).
  Rendered by the top-level handler as a compiler-style diagnostic
  (message + source frames) with no Python traceback.
- InternalError: a bug in fac itself.  Rendered with a full Python
  traceback so it can be diagnosed.

We deliberately do not add subclasses for each kind of user error
(ConfigError, TemplateError, ScriptError, ...).  The top-level handler
only dispatches on UserError vs InternalError, and each UserError
carries a tuple of Frame whose kind records which sort of source
contributed each location.  A single UserError commonly contains
frames of several kinds.
'''

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Frame:
    '''
    A single source location that contributed to a user error.

    Frames accumulate on UserError.frames from the outermost cause to
    the innermost concrete location.

    kind:
        'fac.yaml' -- a line in a fac.yaml file
        'include'  -- an include: statement in a fac.yaml file
        'template' -- a template string (options, description, ...)
        'cmd'      -- a target's cmd: field
        'script'   -- a variable's shell expression
        'llm'      -- an LLM API call
        'python'   -- a Python source location (fallback)
    '''
    kind: Literal[
        'fac.yaml', 'include', 'template', 'cmd', 'script', 'llm', 'python',
    ]
    file: str | None = None
    line: int | None = None
    col: int | None = None
    name: str | None = None
    message: str | None = None


def format_frame(frame):
    '''
    Render a Frame as a single human-readable line.
    '''
    loc = frame.file or '<unknown>'
    if frame.line is not None:
        loc += f':{frame.line}'
        if frame.col is not None:
            loc += f':{frame.col}'
    msg = f'  at {loc}'
    if frame.name:
        msg += f' ({frame.name})'
    if frame.message:
        msg += f': {frame.message}'
    return msg


class FACError(Exception):
    '''
    Base class for all errors raised by fac.

    Prefer raising UserError or InternalError directly.
    '''
    pass


class UserError(FACError):
    '''
    A problem in the user's fac.yaml, templates, scripts, LLM calls, or
    environment.  Rendered without a Python traceback.
    '''
    def __init__(self, message='', *, frames=(), hint=None, context=None):
        super().__init__(message)
        self.message = message
        self.frames = tuple(frames)
        self.hint = hint
        self.context = dict(context) if context else {}

    def add_frame(self, frame):
        '''Return a new UserError with an additional frame appended.'''
        return UserError(
                self.message,
                frames=self.frames + (frame,),
                hint=self.hint,
                context=self.context,
                )


class InternalError(FACError):
    '''
    A bug in fac itself.  Rendered with a full Python traceback.
    '''
    pass


class DirtyRepo(UserError):
    pass


class CommandExecutionError(UserError):
    def __init__(self, returncode, stdout):
        super().__init__(
                f'command failed with exit code {returncode}',
                context={'returncode': returncode, 'stdout': stdout},
                )
        self.returncode = returncode
        self.stdout = stdout

