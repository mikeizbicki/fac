# setup logging
import logging
import contextlib

class RecursiveLogger(logging.Logger):
    """
    A logger class with a recursive subtree feature.

    >>> import sys
    >>> logger = RecursiveLogger('test')
    >>> logger.setLevel(logging.DEBUG)
    >>> handler = logging.StreamHandler(sys.stdout)
    >>> handler.setFormatter(CustomFormatter())
    >>> logger.addHandler(handler)

    >>> logger.info('Root message')
    Root message
    >>> with logger.make_subtree():
    ...     logger.info('First level message')
    ...     logger.info('submessage', submessage=True)
    ...     logger.info('First level message')
    ...     with logger.make_subtree():
    ...         logger.info('Second level message')
    ...         logger.info('Second level message')
    ...         with logger.make_subtree():
    ...             logger.info('Third level message')
    ...     logger.info('First level message again')
    ...     with logger.make_subtree():
    ...         logger.info('Second level message')
    ├── First level message
    │   submessage
    ├── First level message
    │   ├── Second level message
    │   ├── Second level message
    │   │   ├── Third level message
    ├── First level message again
    │   ├── Second level message
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.indent_level = 0
        self.log_stack = []

    @contextlib.contextmanager
    def make_subtree(self):
        self.indent_level += 1
        try:
            yield
        finally:
            self.indent_level -= 1

    def _log(self, level, msg, args, submessage=False, **kwargs):
        extra = kwargs.get('extra', {})
        if self.indent_level > 0:
            if submessage:
                extra['tree_prefix'] = '│   ' * self.indent_level
            else:
                extra['tree_prefix'] = '│   ' * (self.indent_level - 1) + '├── '
        else:
            extra['tree_prefix'] = ''
        kwargs['extra'] = extra
        super()._log(level, msg, args, **kwargs)


def with_subtree(logger_obj):
    """
    This decorator creates a logging subtree context around the decorated function.
    Whenever the function is called (usually recursively),
    a new indentation level will appear in the logger.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            with logger_obj.make_subtree():
                return func(*args, **kwargs)
        return wrapper
    return decorator


handler = logging.StreamHandler()
class CustomFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno == logging.INFO:
            self._style._fmt = '%(tree_prefix)s%(message)s'
        else:
            self._style._fmt = '%(tree_prefix)s[%(levelname)s] %(message)s'
        return super().format(record)
handler.setFormatter(CustomFormatter(datefmt='%Y-%m-%d %H:%M:%S'))
logger = RecursiveLogger(__name__)
logger.addHandler(handler)
logger.propagate = False
logger.setLevel(logging.INFO)

# add custom TRACE log level that sits below DEBUG
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, 'TRACE')
def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)
logging.Logger.trace = trace


