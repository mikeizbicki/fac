from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Optional, Set, Any, Literal
import asyncio
import logging
import os
import signal
import sys
import threading
import time

from fac.Fac import Fac, FacSettings
from fac.Logging import logger, with_subtree
import fac.Errors

import git
from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, CliApp, SettingsConfigDict
import hypercorn

from fastapi.responses import FileResponse
from facd import git_routes
from facd import monitor_jobs


################################################################################
# FastAPI setup
################################################################################

@asynccontextmanager
async def lifespan(app: FastAPI):
    if app.args.unsafe_multithread:
        logger.critical('--unsafe_multithread enabled, but build_daemon is not thread safe')
        def run_daemon_in_thread():
            asyncio.run(app.state.build_daemon())
        daemon_task = asyncio.create_task(asyncio.to_thread(run_daemon_in_thread))

    else:
        daemon_task = asyncio.create_task(app.state.build_daemon())

    yield

    # cleanup code here
    logger.warning('FastAPI lifespan ended')
    app.state.path_routes.shutdown()
    await git_routes.shutdown_git_routes()
    await asyncio.sleep(1)

    try:
        daemon_task.cancel()
        await daemon_task

    # When the server shuts down (e.g. by pressing CTRL-C)
    # and the build_daemon is in the middle of a build,
    # these are all common errors that get thrown.
    # The exact error depends on where in the build process shutdown is triggered.
    except (
            asyncio.CancelledError,
            git.exc.GitCommandError,
            fac.Errors.FACError,
            ValueError,
            BrokenPipeError
            ):
        pass

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
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(handler)

async def log_generator():
    queue = asyncio.Queue(maxsize=100)
    log_queues.add(queue)
    try:
        yield "data: connected\n\n"
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


class AddTargetRequest(BaseModel):
    target: str
    required_for: Optional[Any] = None
    include_prompt: Optional[str] = None
    include_old: bool = False
    include_paths: Optional[Any] = None
    tasks: Set[str] = {'build'}


@app.post('/add_target')
def add_target_endpoint(request: AddTargetRequest):
    '''
    Registers a target with the build system.

    Arguments:
    - target (str): the target to be built; all variables must be specified; supports globstar (**)-style pattern matching
    - include_prompt (str): allows specifying additional build instructions for the target
    - include_old (bool): should the old file be included if rebuilding?
    - tasks [str]:
        - "build": (default) build the file only if needed
        - "overwrite": always build the file, overwriting existing contents
        - "dryrun": register the file with the build system, but do not build
    '''
    app.state.add_target(
        target=request.target,
        required_for=request.required_for,
        include_prompt=request.include_prompt,
        include_old=request.include_old,
        include_paths=request.include_paths,
        tasks=request.tasks,
    )
    return {"status": "success"}

################################################################################
# run the server
################################################################################

class FacdSettings(FacSettings):
    '''Settings for the facd daemon, including server and build options.'''
    model_config = SettingsConfigDict(
        cli_parse_args=True,
        cli_prog_name='facd',
        env_prefix='FAC_',
    )
    server: Literal['hypercorn', 'uvicorn'] = 'hypercorn'
    unsafe_multithread: bool = False
    dryrun_target: str = '**'

def main():
    settings = FacdSettings()

    app.args = settings
    logger.setLevel(settings.loglevel)

    # register state routes
    try:
        state = Fac(
            allow_dirty=settings.allow_dirty,
            auto_commit=settings.auto_commit,
            settings=settings,
        )
    except fac.Errors.FACError:
        return 1
    app.state = state

    # perform a dryrun to register files with facd
    state.add_target(settings.dryrun_target, tasks=set())

    # register routes
    app.include_router(state.router)
    app.include_router(state.path_routes.router)
    app.include_router(git_routes.router)
    monitor_jobs.set_build_state(state)
    app.include_router(monitor_jobs.router)

    # start the web server
    if settings.server == 'hypercorn':
        from hypercorn.asyncio import serve
        from hypercorn.config import Config
        config = Config()
        # NOTE:
        # There was a bad bug when using IPv4 that caused connections to localhost
        # to sometimes break in very heisenbugish ways.  Binding to IPv6 seems to
        # solve this problem.
        config.bind = ['[::]:8080']
        config.graceful_timeout = 2.0

        async def _run():
            shutdown_event = asyncio.Event()
            loop = asyncio.get_running_loop()

            def _handle_signal():
                logger.error('Force exiting...')
                shutdown_event.set()
                os._exit(1)

            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _handle_signal)
            await serve(app, config, shutdown_trigger=shutdown_event.wait)

        asyncio.run(_run())

    elif settings.server == 'uvicorn':
        import uvicorn
        uvicorn.run(
                app,
                host='::',
                port=8080,
                timeout_graceful_shutdown=5,
                log_level='warning',
                )

if __name__ == '__main__':
    main()
