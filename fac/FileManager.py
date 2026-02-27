import asyncio
import json
from typing import AsyncGenerator

from fac.util.FastAPI import *
from fac.util.targets import *

from fastapi import Request
from fastapi.responses import StreamingResponse
from watchfiles import awatch, Change


class FileManager(Routable):
    def __init__(self, targets_dict):
        self.targets_dict = targets_dict
        self.files: dict[str, dict] = {}
        self._subscribers: list[asyncio.Queue] = []
        self._shutdown = False
        super().__init__()

    async def start(self):
        self._watch_task = asyncio.create_task(self._watch_files())

    async def _watch_files(self):
        async for changes in awatch(".", stop_event=self._stop_event):
            for change_type, path in changes:
                if path not in self.files:
                    continue
                if change_type == Change.deleted:
                    self.files[path]['status'] = 'deleted'
                self._notify(path)

    async def shutdown(self):
        self._shutdown = True
        self._stop_event.set()
        if self._watch_task:
            await self._watch_task
        for queue in self._subscribers:
            await queue.put(None)

    @property
    def _stop_event(self):
        if not hasattr(self, "_stop_event_obj"):
            self._stop_event_obj = asyncio.Event()
        return self._stop_event_obj

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
            target, variables = targets[0]
            mime = self.targets_dict[target]['mime-type']
        else:
            raise ValueError('path corresponds to multiple targets; this should never happen with a correct fac.yaml file')
        self.files[path] = {
                'status': 'fresh',
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
        if info['status'] == 'deleted':
            content = None
        else:
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

    async def _event_stream(self, request: Request) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            for path in self.files:
                if await request.is_disconnected():
                    return
                event = self._file_event(path)
                yield f"data: {json.dumps(event)}\n\n"
            while not self._shutdown:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    if event is None:
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    continue
        finally:
            self._subscribers.remove(queue)

    @route("/monitor_files", methods=["GET"])
    async def monitor_files(self, request: Request) -> StreamingResponse:
        '''
        Stream file events via Server-Sent Events (SSE).

        On connection, sends the current state of all files that correspond to a target in the 'fac.yaml' file.
        Then streams real-time updates whenever a file is added or its status changes.

        Each event is a JSON object with fields:
        - path
        - mime-type
        - content (may be None for large files) 
        - target: the target in 'fac.yaml' that the specified path was generated from
        - status:
            - "fresh": the file exists and is up-to-date
            - "stale": the file exists but needs to be rebuilt because dependencies have been modified
            - "deleted": the file has been deleted
        ```
        '''
        # FIXME:
        # The graceful shutdown code in this route does not work.
        # When someone connects to this route, facd will hang on shutdown.
        return StreamingResponse(
            self._event_stream(request),
            media_type="text/event-stream",
        )
