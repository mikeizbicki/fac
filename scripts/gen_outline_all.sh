#!/bin/bash

set -e

for story in stories/*; do
    if [ -d "$story" ]; then
        echo "gen_outline.sh $story"
        ./scripts/gen_outline.sh "$story"
    fi
done
