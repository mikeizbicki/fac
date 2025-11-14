#!/usr/bin/env python3
'''
`fac` is a build system for LLM-based agentic projects.
The Latin verb `facio` means to do/make, and fac is the imperative form.
'''

from dataclasses import fields
import typing

from fac.BuildSystem import *


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


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('targets', nargs='*')

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
    args = parser.parse_args()

    bs_args = dict(**vars(args))
    del bs_args['targets']
    build_system = BuildSystem(**bs_args)

    try:
        with build_system:
            build_system.build_targets(args.targets)
    except (DirtyRepo, NoTargetsMatched):
        return 1


if __name__ == '__main__':
    main()
