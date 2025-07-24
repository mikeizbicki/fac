import logging

# add custom TRACE log level that sits below DEBUG
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, 'TRACE')
def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)
logging.Logger.trace = trace

# setup logging
class DeduplicatingHandler(logging.StreamHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_message = None
        self.last_level = None

    def emit(self, record):
        current_message = record.getMessage()
        current_level = record.levelno

        if current_message == self.last_message and current_level == self.last_level:
            return  # Skip duplicate message

        self.last_message = current_message
        self.last_level = current_level
        super().emit(record)
handler = DeduplicatingHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    '%Y-%m-%d %H:%M:%S'
))
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.propagate = False
logger.setLevel(logging.DEBUG)


import json

def load_jsonl(file_path, buffer_size=8192):
    """
    Load JSONL (JSON Lines) file as a generator without loading the entire file into memory.

    This function can handle:
    - Standard JSONL format (one JSON object per line)
    - Multi-line JSON objects with pretty formatting
    - Mixed formats within the same file
    - Large files that don't fit in memory

    """
    decoder = json.JSONDecoder()
    buffer = ""

    with open(file_path, 'r') as f:
        while True:
            chunk = f.read(buffer_size)
            if not chunk:
                break
            buffer += chunk

            # Try to decode objects from buffer
            while buffer.strip():
                buffer = buffer.lstrip()
                if not buffer:
                    break

                try:
                    obj, end_idx = decoder.raw_decode(buffer)
                    yield obj
                    buffer = buffer[end_idx:]
                except json.JSONDecodeError:
                    # Need more data, break and read next chunk
                    break

        # Process any remaining data in buffer
        if buffer.strip():
            try:
                obj, _ = decoder.raw_decode(buffer.strip())
                yield obj
            except json.JSONDecodeError:
                pass  # Invalid JSON at end of file
