#!/usr/bin/env python3
'''
`fac` is a build system for LLM-based agentic projects.
The Latin verb `facio` means to do/make, and fac is the imperative form.
'''

from dataclasses import fields
import typing

from fac.BuildSystem import BuildSystem


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
    args = parser.parse_args()

    build_system = BuildSystem()
    for target in build_system.full_config:
        print(target)


if __name__ == '__main__':
    main()

