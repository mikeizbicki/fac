#!/usr/bin/env python3
'''
CLI tool for generating images using the LLM class.
'''

import argparse
import asyncio
import sys

from fac.Logging import logger
from fac.LLM import LLM


class OptionsAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        d = getattr(namespace, self.dest) or {}
        s = values.strip()
        if s.startswith('{'):
            d.update(json.loads(s))
        else:
            k, _, v = s.partition('=')
            d[k] = v
        setattr(namespace, self.dest, d)


def main():
    parser = argparse.ArgumentParser(
        prog='pinge',
        description='Generate images using LLMs',
    )
    parser.add_argument(
        '-m', '--model',
        help='Model to use for image generation',
    )
    parser.add_argument(
        '-p', '--path',
        default='output.png',
        help='Output file path (default: output.png)',
    )
    parser.add_argument(
        '-a', 
        )
    parser.add_argument(
        '-o', '--options', action=OptionsAction, default={},
        help='Specify options for the input model',
        )
    parser.add_argument('--loglevel', default='DEBUG')
    parser.add_argument('--dryrun', action='store_true')
    parser.add_argument(
        'prompt',
        nargs='?',
        help='Prompt for image generation (reads from stdin if not provided)',
    )

    args = parser.parse_args()
    logger.setLevel(args.loglevel)

    # Get prompt from argument or stdin
    if args.prompt is not None:
        prompt = args.prompt
    else:
        prompt = sys.stdin.read().strip()

    if not prompt:
        parser.error('No prompt provided')

    # Build data dict for image generation
    data = {'prompt': prompt}
    if args.model:
        data['model'] = args.model
    for opt in args.options:
        data[opt] = args.options[opt]
    if args.a:
        data['reference_images'] = [args.a]

    # Generate image
    llm = LLM()
    asyncio.run(llm.image_async(args.path, data, dryrun=args.dryrun))
    llm.log_usage()


if __name__ == '__main__':
    main()
