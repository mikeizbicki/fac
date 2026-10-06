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

import contextlib
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
        '''
        Return a UserError with `frame` appended, unless it is already
        present.  Idempotency matters because an error can be caught,
        re-raised, and caught again at two boundaries; without it, the
        same frame would appear twice in the rendered diagnostic.
        '''
        if frame in self.frames:
            return self
        return UserError(
                self.message,
                frames=self.frames + (frame,),
                hint=self.hint,
                context=self.context,
                )

    # alias so callers can read it as the symmetric form of frame_scope
    with_frame = add_frame


@contextlib.contextmanager
def frame_scope(frame):
    '''
    Attach `frame` to any UserError raised inside the with block.

    This is how outer frames (e.g. a fac.yaml line) get attached to an
    error raised by a lower layer (e.g. a template or a script) without
    the lower layer needing to know about its callers.

    The frame is attached on __exit__, so an error that escapes an
    async task scheduled from inside the block still carries it -- an
    alternative design based on a contextvar frame stack would lose the
    frame when the block popped.
    '''
    try:
        yield
    except UserError as e:
        raise e.add_frame(frame) from e


def render_user_error(e, logger):
    '''
    Print a UserError as a compiler-style diagnostic: the message, each
    source frame, the context data, and the hint -- but no Python
    traceback (which is reserved for InternalError and unexpected
    exceptions).
    '''
    logger.error(e.message or type(e).__name__)
    for frame in e.frames:
        logger.error(format_frame(frame), submessage=True)
    for key, value in e.context.items():
        logger.error({key: value}, submessage=True)
    if e.hint:
        logger.error(f'  hint: {e.hint}', submessage=True)


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

