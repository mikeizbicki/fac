#!/bin/env python3

import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('path')
parser.add_argument('query')
parser.add_argument('--num_results', default=20)
parser.add_argument('--lang', default='en')
parser.add_argument('--region', default='us')
args = parser.parse_args()

os.path.makedirs

from googlesearch import search
results = search(
        args.query,
        unique=True,
        num_results=args.num_results,
        lang=args.lang,
        region=args.region,
        )

