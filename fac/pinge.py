#!/usr/bin/env python3
'''
CLI tool for generating images using the LLM class.
'''

import argparse
import asyncio
import sys

from fac.LLM import LLM


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
        '-o', '--output',
        default='output.png',
        help='Output file path (default: output.png)',
    )
    parser.add_argument(
        'prompt',
        nargs='?',
        help='Prompt for image generation (reads from stdin if not provided)',
    )

    args = parser.parse_args()

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

    # Generate image
    llm = LLM()
    asyncio.run(llm.image_async(args.output, data))
    llm.log_usage()


if __name__ == '__main__':
    main()
