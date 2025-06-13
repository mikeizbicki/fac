#!/bin/sh

set -ex

PROJECT_PATH=test_project
CMD="./scripts/generate.py --config-path=$PROJECT_PATH/config.yaml"

# incremental building
$CMD 'test_project/outline.json' 
$CMD 'test_project/sub$LEVEL1/outline.json'
$CMD 'test_project/sub$LEVEL1/sub$LEVEL2/outline.json'
$CMD 'test_project/final.txt'

# build the full project from scratch;
# the `git clean` command removes all files that have been built from previous test runs
RESET_PROJECT="cd $PROJECT_PATH; git clean -fd; cd -;"
$RESET_PROJECT; $CMD 'test_project/outline.json' 
$RESET_PROJECT; $CMD 'test_project/sub$LEVEL1/outline.json'
$RESET_PROJECT; $CMD 'test_project/sub$LEVEL1/sub$LEVEL2/outline.json'
$RESET_PROJECT; $CMD 'test_project/final.txt'
