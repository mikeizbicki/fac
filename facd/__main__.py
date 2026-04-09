from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Optional, Set, Any, Literal
import asyncio
import logging
import sys
import threading
import time

from fac.Errors import *
from fac.Fac import Fac
from fac.Logging import *

from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn

from fastapi.responses import FileResponse
from facd import git_routes
from facd import monitor_jobs

################################################################################
# FastAPI setup
################################################################################

@asynccontextmanager
async def lifespan(app: FastAPI):

    yield

    # cleanup code here
    await state.built_paths.shutdown()
    await git_routes.shutdown_git_routes()

app = FastAPI(title="fac build server", lifespan=lifespan)

# prepare /static mount point
static_path = files("facd") / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")

# prepare templates
templates_path = files("facd") / "static"
templates = Jinja2Templates(directory=str(templates_path))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/favicon.ico")
def favicon():
    return FileResponse(static_path / "favicon.ico")


################################################################################
# streaming client logs
################################################################################

# Store connected client queues
log_queues: Set[asyncio.Queue] = set()

class BroadcastHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        for queue in log_queues:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass

# Attach handler to your build system logger
#logger = logging.getLogger("fac")  # adjust to match your logger name
handler = BroadcastHandler()
#handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(handler)

async def log_generator():
    queue = asyncio.Queue(maxsize=100)
    log_queues.add(queue)
    try:
        while True:
            msg = await queue.get()
            yield f"data: {msg}\n\n"
    finally:
        log_queues.discard(queue)

@app.get("/logs_stream")
async def stream_logs():
    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.get('/list_targets', response_model=dict[str, Any])
def list_targets():
    '''
    Returns a dictionary of targets defined in the 'fac.yaml' file.
    The keys are targets and values are config information describing how to build the targets.

    ---

    A target is a string that may contain shell-like variables
    that describes a formula for generating paths.

    For example:

    1. The target "example.json" contains no variables and will always resolve to path "example.json".

    2. The target "chapters/$CHAPTER/outline.json" with CHAPTER=['0001', '0002', '0003']
        will resolve to the three paths:
        - 'chapters/0001/outline.json'
        - 'chapters/0002/outline.json'
        - 'chapters/0003/outline.json'

    The web API exposes methods for working with targets and their corresponding paths,
    but does not expose an interface for working with the variables.
    The variable definitions are exposed in the config values returned by this endpoint for debug purposes,
    but they are processed internally by the webserver and shouldn't be used in the web app.
    Any web applications must be built to handle arbitrary paths existing for each target.
    '''
    return app.state.targets_dict

def build_daemon(state):
    '''
    Creates a daemon thread that will continuously build any targets added with `add_target`.
    This method is used by facd to ensure that the /add_target endpoint results in builds.
    '''
    def daemon_loop():
        while True:
            state.build_all()
            time.sleep(1)
    state._daemon_thread = threading.Thread(target=daemon_loop, daemon=True)
    state._daemon_thread.start()
    return state._daemon_thread

################################################################################
# run the server
################################################################################

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow_dirty', action='store_true')
    args = parser.parse_args()

    # register state routes
    state = Fac(
        allow_dirty=args.allow_dirty,
        )
    app.state = state
    #state.file_manager.start()

    # perform a dryrun to register all files with facd;
    # build_all=False allows facd startup to continue,
    # and the build_daemon will run the build concurrently
    # in the background thread
    state.full_dryrun(build_all=False)
    build_daemon(state)

    # register routes
    app.include_router(state.router)
    app.include_router(state.file_manager.router)
    app.include_router(git_routes.router)
    monitor_jobs.set_build_state(state)
    app.include_router(monitor_jobs.router)

    # start the web server
    uvicorn.run(
            app,
            host='localhost',
            port=8080,
            timeout_graceful_shutdown=1,
            log_level='warning',
            )

if __name__ == '__main__':
    main()
