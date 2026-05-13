#!/usr/bin/env python3
'''
`fac` is a build system for LLM-based agentic projects.
The Latin verb `facio` means to do/make, and fac is the imperative form.
'''

from dataclasses import fields, dataclass
import typing
from fac.Config import pprint_targets
from fac.Fac import Fac
from fac.Logging import logger

@dataclass
class BuildSystem:
    # general settings
    config_file: str = 'fac.yaml'
    debug: bool = False
    trace: bool = False
    jobs: int = 1

    # debug actions
    print_config: bool = False
    print_prompt: bool = False

    # build settings
    overwrite: bool = False
    dryrun: bool = False
    lock: bool = False
    unlock: bool = False
    include_prompt: str = None
    include_old: bool = False
    include_paths: list[str] = None
    allow_dirty: bool = False
    auto_commit: bool = True

    def __post_init__(self):
        if self.dryrun:
            self.auto_commit = False
        self.build_state = Fac(
                self.config_file,
                allow_dirty=self.allow_dirty,
                auto_commit=self.auto_commit,
                print_prompt=self.print_prompt,
                )
        if self.debug:
            logger.setLevel('DEBUG')
        if self.trace:
            logger.setLevel('TRACE')

        if self.print_config:
            pprint_targets(self.build_state.targets_dict)

    def build_targets(self, targets):
        # actually build the targets
        for target in targets:
            tasks = {'build'}
            if self.dryrun:
                tasks = {}
            if self.overwrite:
                tasks = {'overwrite'}
            if self.lock:
                tasks = {'lock'}
            if self.unlock:
                tasks = {'unlock'}
            self.build_state.add_target(
                    target,
                    include_prompt=self.include_prompt,
                    include_old=self.include_old,
                    include_paths=self.include_paths,
                    tasks=frozenset(tasks),
                    )
        self.build_state.build_all()


def main():
    from fac.Errors import FACError
    import fac.Config
    import fac.Fac
    import argcomplete
    import argparse

    def str2bool(v):
        '''
        For use with argparse and creating boolean parameters.
        '''
        if isinstance(v, bool):
            return v
        if v.lower() in ('yes', 'true', 't', 'y', '1'):
            return True
        elif v.lower() in ('no', 'false', 'f', 'n', '0'):
            return False
        else:
            raise argparse.ArgumentTypeError('Boolean value expected.')

    parser = argparse.ArgumentParser()
    parser.add_argument('targets', nargs='*').completer = fac.Config.fac_targets_completer
    parser.add_argument('--dev', action='store_true', help='run in developer mode')

    # BuildSystem uses the @dataclass decorator so that all of its fields (class attributes with type annotations) are parameters to the constructor;
    # the code below loops over these fields, and for each field we add it as an argparse parameter;
    # this means that the code below shouldn't need to be modified to add new parameters to the CLI;
    # whenever we add new fields to BuildSystem, they will automatically be added to the CLI
    for field in fields(BuildSystem):
        if field.name != 'targets':
            field.name, field.default, field.type
            name = f'--{field.name}'
            if typing.get_origin(field.type) is typing.Literal:
                choices = typing.get_args(field.type)
                parser.add_argument(name, choices=choices, default=field.default)
            elif field.type == bool:
                if field.default == False:
                    parser.add_argument(name, action='store_true')
                else:
                    parser.add_argument(name, type=str2bool, default=True)
            elif field.type == list[str]:
                parser.add_argument(name, default=None, type=str, nargs='*')
            else:
                parser.add_argument(name, default=field.default, type=field.type)
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    if args.dev:
        # on error go into interactive python
        import sys
        import traceback
        import pdb
        def hook(type, value, tb):
            traceback.print_exception(type, value, tb)
            pdb.post_mortem(tb)
        sys.excepthook = hook

    import fac.Fac
    bs_args = dict(**vars(args))
    del bs_args['targets']
    del bs_args['dev']

    try:
        build_system = BuildSystem(**bs_args)
        build_system.build_targets(args.targets)
    except FACError:
        pass

if __name__ == '__main__':
    main()
