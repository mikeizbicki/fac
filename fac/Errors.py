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

    >>> format_frame(Frame(kind='fac.yaml', file='sub/fac.yaml', line=3))
    '  at sub/fac.yaml:3'
    >>> format_frame(Frame(kind='fac.yaml', file='sub/fac.yaml', line=3, col=7, name='foo.txt'))
    '  at sub/fac.yaml:3:7 (foo.txt)'
    >>> format_frame(Frame(kind='template', name='options.model'))
    '  at <unknown> (options.model)'
    >>> format_frame(Frame(kind='script', name='X', message='foo.txt'))
    '  at <unknown> (X): foo.txt'
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

        >>> e = UserError('boom')
        >>> e.frames
        ()
        >>> f = Frame(kind='fac.yaml', file='fac.yaml', line=3)
        >>> e2 = e.add_frame(f)
        >>> e2.frames
        (Frame(kind='fac.yaml', file='fac.yaml', line=3, col=None, name=None, message=None),)
        >>> e.frames  # the original is unchanged
        ()

        Adding the same frame again is a no-op (idempotent):

        >>> e2.add_frame(f).frames
        (Frame(kind='fac.yaml', file='fac.yaml', line=3, col=None, name=None, message=None),)
        >>> e2.add_frame(Frame(kind='fac.yaml', file='fac.yaml', line=3)).frames
        (Frame(kind='fac.yaml', file='fac.yaml', line=3, col=None, name=None, message=None),)

        A structurally different frame is added as a new layer:

        >>> e3 = e2.add_frame(Frame(kind='template', name='options.model'))
        >>> len(e3.frames)
        2
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

    >>> try:
    ...     with frame_scope(Frame(kind='fac.yaml', line=10)):
    ...         raise UserError('boom')
    ... except UserError as e:
    ...     print(e.message)
    ...     print(e.frames[0].line)
    boom
    10

    Non-UserErrors pass through unchanged:

    >>> try:
    ...     with frame_scope(Frame(kind='fac.yaml', line=10)):
    ...         raise ValueError('not a UserError')
    ... except ValueError:
    ...     print('ValueError not wrapped')
    ValueError not wrapped

    Nested scopes stack inner-first, so the more specific frame comes
    before the outer one:

    >>> try:
    ...     with frame_scope(Frame(kind='fac.yaml', line=1)):
    ...         with frame_scope(Frame(kind='template', name='x')):
    ...             raise UserError('boom')
    ... except UserError as e:
    ...     [f.kind for f in e.frames]
    ['template', 'fac.yaml']
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

    The doctests use a minimal fake logger that records each call, so
    that the diagnostic's structure can be checked without depending
    on the real logger's formatting (colors, tree prefixes, yaml
    rendering of non-string messages).

    >>> class FakeLogger:
    ...     def __init__(self):
    ...         self.calls = []
    ...     def error(self, msg, **kwargs):
    ...         self.calls.append(msg)
    >>> lg = FakeLogger()
    >>> e = UserError(
    ...     'something went wrong',
    ...     frames=(Frame(kind='fac.yaml', file='fac.yaml', line=5),),
    ...     hint='try fixing it',
    ... )
    >>> render_user_error(e, lg)
    >>> lg.calls[0]
    'something went wrong'
    >>> lg.calls[1]
    '  at fac.yaml:5'
    >>> lg.calls[2]
    '  hint: try fixing it'

    Context key/value pairs are passed one at a time:

    >>> lg = FakeLogger()
    >>> render_user_error(UserError('boom', context={'var': 'TOPIC'}), lg)
    >>> lg.calls
    ['boom', {'var': 'TOPIC'}]
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

