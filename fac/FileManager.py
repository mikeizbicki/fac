import asyncio
import json
from typing import AsyncGenerator

from fastapi.responses import StreamingResponse

from fac.util.FastAPI import *
from fac.util.targets import *


class FileManager(Routable):
    def __init__(self, targets_dict):
        self.targets_dict = targets_dict
        self.files: dict[str, dict] = {}
        self._subscribers: list[asyncio.Queue] = []
        super().__init__()

    def make_stale(self, path: str) -> None:
        if path not in self.files or self.files[path]["status"] == "stale":
            return
        self.files[path]["status"] = "stale"
        self._notify(path)

    ##############################
    # set interface
    ##############################

    def add(self, path: str) -> None:
        if path in self.files:
            return
        targets = match_pattern_starstar(self.targets_dict, path)
        if len(targets) == 0: # happens when path doesn't correspond
            target = path
            mime = 'unknown'
        elif len(targets) == 1:
            target = targets[0]
            mime = self.targets_dict[target]['mime-type']
        else:
            raise ValueError('path corresponds to multiple targets; this should never happen with a correct fac.yaml file')
        self.files[path] = {
                'status': 'built',
                'target': target,
                'mime-type': mime,
                }
        self._notify(path)

    def __contains__(self, path: str) -> bool:
        return path in self.files

    def __len__(self) -> int:
        return len(self.files)

    def __iter__(self):
        return iter(self.files)

    ##############################
    # FastAPI
    ##############################

    def _file_event(self, path: str) -> dict:
        info = self.files[path]
        with open(path, "r") as f:
            content = f.read()
        return {
            "path": path,
            "content": content,
            **info
        }

    def _notify(self, path: str):
        event = self._file_event(path)
        for queue in self._subscribers:
            queue.put_nowait(event)

    async def _event_stream(self) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            for path in self.files:
                event = self._file_event(path)
                yield f"data: {json.dumps(event)}\n\n"
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            self._subscribers.remove(queue)

    @route("/monitor_files", methods=["GET"])
    async def monitor_files(self) -> StreamingResponse:
        '''
        Stream file events via Server-Sent Events (SSE).

        On connection, sends the current state of all files that correspond to a target in the 'fac.yaml' file.
        Then streams real-time updates whenever a file is added or its status changes.

        Each event is a JSON object with fields:
        - path: file path
        - target: the target in 'fac.yaml' that the specified path was generated from
        - status: "fresh", "stale", or other future statuses
        - mime-type: file type (currently always "text")
        - content: current file contents
        ```
        '''
        return StreamingResponse(
            self._event_stream(),
            media_type="text/event-stream",
        )
