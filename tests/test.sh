#!/bin/sh

set -ex

CMD="./scripts/generate.py --config-path=test_project/config.yaml"

# these should all build with no errors
$CMD 'test_project/outline.json' 
$CMD 'test_project/sub$LEVEL1/outline.json'
