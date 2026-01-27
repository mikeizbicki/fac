# stdlib imports
from collections import deque
import asyncio
import contextlib
import contextvars
import logging

# external lib imports
import json_repair
import jsonschema
import yaml


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
        # Context variable to store buffered logs per async task
        self._log_buffer = contextvars.ContextVar('log_buffer', default=None)

    @contextlib.contextmanager
    def make_subtree(self):
        self.indent_level += 1
        try:
            yield
        finally:
            self.indent_level -= 1

    @contextlib.contextmanager
    def buffer_logs(self):
        """Context manager to buffer logs until the context exits."""
        # Create a new buffer for this context
        buffer = deque()
        token = self._log_buffer.set(buffer)
        try:
            yield
        finally:
            # Flush all buffered logs
            current_buffer = self._log_buffer.get(None)
            if current_buffer:
                for log_record in current_buffer:
                    # Call the original _log method to actually emit the log
                    super()._log(log_record['level'], log_record['msg'], log_record['args'], **log_record['kwargs'])
            # Reset the context variable
            self._log_buffer.reset(token)

    def _log(self, level, msg, args, submessage=False, max_line_length=None, **kwargs):

        # Auto-format non-string objects as YAML
        if not isinstance(msg, str):
            yaml_str = yaml.dump(msg, default_flow_style=False, allow_unicode=True, indent=2, width=float('inf')).rstrip('\n')
            lines = yaml_str.split('\n')
            for i, line in enumerate(lines):
                # Truncate long lines
                if max_line_length and len(line) > max_line_length:
                    line = line[:max_line_length] + '...'
                # First line uses passed submessage, rest are always submessages
                self._log(level, line, args, submessage=(submessage if i == 0 else submessage), **kwargs)
            return

        # Truncate long string messages too
        if max_line_length and len(msg) > max_line_length:
            msg = msg[:max_line_length] + '...'

        # add the depth level annotaions
        extra = kwargs.get('extra', {})
        if self.indent_level > 0:
            if submessage:
                extra['tree_prefix'] = '│   ' * self.indent_level
            else:
                extra['tree_prefix'] = '│   ' * (self.indent_level - 1) + '├── '
        else:
            extra['tree_prefix'] = ''
        kwargs['extra'] = extra
        
        # Check if we should buffer this log
        buffer = self._log_buffer.get(None)
        if buffer is not None:
            # Store the log record in the buffer
            buffer.append({
                'level': level,
                'msg': msg,
                'args': args,
                'kwargs': kwargs
            })
        else:
            # Normal logging behavior
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


def with_buffered_logs(logger_obj):
    """
    This decorator buffers all logs during function execution and flushes them when the function returns.
    Works with both sync and async functions.
    """
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                with logger_obj.buffer_logs():
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs):
                with logger_obj.buffer_logs():
                    return func(*args, **kwargs)
            return sync_wrapper
    return decorator


class CustomFormatter(logging.Formatter):
    # ANSI color codes
    COLORS = {
        #'DEBUG': '\033[36m',      # Cyan
        #'INFO': '\033[32m',       # Green
        #'WARNING': '\033[33m',    # Yellow/Orange
        'WARNING': '\033[38;5;208m',    # Yellow/Orange
        'ERROR': '\033[31m',      # Red
        #'ERROR': '\033[91m',      # Red
        #'ERROR': '\033[38;2;178;34;34m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        if record.levelname in self.COLORS:
            startcolor = self.COLORS[record.levelname]
            stopcolor = self.RESET
        else:
            startcolor = ''
            stopcolor = ''
        if record.levelno == logging.INFO:
            self._style._fmt = '%(tree_prefix)s%(message)s'
        else:
            self._style._fmt = f'%(tree_prefix)s{startcolor}[%(levelname)s] %(message)s{stopcolor}'
        message = super().format(record)
        return message

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(CustomFormatter(datefmt='%Y-%m-%d %H:%M:%S'))
file_handler = logging.FileHandler('.fac.log')
file_handler.setFormatter(CustomFormatter(datefmt='%Y-%m-%d %H:%M:%S'))
logger = RecursiveLogger(__name__)
logger.addHandler(stream_handler)
logger.addHandler(file_handler)
logger.propagate = False
logger.setLevel(logging.INFO)

# add custom TRACE log level that sits below DEBUG
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, 'TRACE')
def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)
logging.Logger.trace = trace
file_handler.setLevel('TRACE')
