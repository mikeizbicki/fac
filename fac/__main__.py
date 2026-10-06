#!/usr/bin/env python3
'''
`fac` is a build system for LLM-based agentic projects.
The Latin verb `facio` means to do/make, and fac is the imperative form.
'''

import sys
import typing
from fac.Config import pprint_targets
from fac.Errors import InternalError, UserError, format_frame
from fac.Fac import Fac, FacSettings
from fac.Logging import logger
from pydantic_settings import SettingsConfigDict, CliPositionalArg


class CLISettings(FacSettings):
    model_config = SettingsConfigDict(
        cli_parse_args=True,
        cli_prog_name='fac',
        cli_implicit_flags=True,
        env_prefix='FAC_',
    )
    targets: CliPositionalArg[list[str]] = []
    dryrun: bool = False
    overwrite: bool = False
    lock: bool = False
    unlock: bool = False
    include_prompt: str | None = None
    include_old: bool = False
    include_paths: list[str] | None = None

    print_context_states: bool = False


def _render_user_error(e):
    '''
    Print a UserError without a Python traceback.

    Renders the message, then each Frame, then the context dict, then
    the hint.  This is a compiler-style diagnostic: the goal is for the
    user to be able to trace back to a line in a fac.yaml (or a
    template, or a script) without seeing any of fac's own code.
    '''
    logger.error(e.message or type(e).__name__)
    for frame in e.frames:
        logger.error(format_frame(frame), submessage=True)
    for key, value in e.context.items():
        logger.error({key: value}, submessage=True)
    if e.hint:
        logger.error(f'  hint: {e.hint}', submessage=True)


def main():
    settings = CLISettings()
    logger.setLevel(settings.loglevel)
    try:
        fac = Fac(settings)

        for target in settings.targets:
            tasks = {'build'}
            if settings.dryrun:
                tasks = {}
            if settings.overwrite:
                tasks = {'overwrite'}
            if settings.lock:
                tasks = {'lock'}
            if settings.unlock:
                tasks = {'unlock'}
            fac.add_target(
                    target,
                    include_prompt=settings.include_prompt,
                    include_old=settings.include_old,
                    include_paths=settings.include_paths,
                    tasks=frozenset(tasks),
                    )
        fac.build_all()

        if settings.print_context_states:
            import json
            states = json.dumps(fac.context_states(), indent=2)
            print(states)
    except UserError as e:
        _render_user_error(e)
        sys.exit(1)
    except InternalError:
        logger.error('internal error in fac; please report', exc_info=True)
        sys.exit(2)
    except Exception:
        logger.error('unexpected error in fac; please report', exc_info=True)
        sys.exit(2)


if __name__ == '__main__':
    main()
