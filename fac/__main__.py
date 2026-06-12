#!/usr/bin/env python3
'''
`fac` is a build system for LLM-based agentic projects.
The Latin verb `facio` means to do/make, and fac is the imperative form.
'''

import typing
from fac.Config import pprint_targets
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

def main():
    settings = CLISettings()
    logger.setLevel(settings.loglevel)
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
        print(fac.context_states())


if __name__ == '__main__':
    main()
