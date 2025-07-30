#!/bin/sh

set -ex
cd examples/test_project
alias fac='python3 -m fac'

# incremental building
fac 'outline.json' 
fac 'sub$LEVEL1/outline.json'
fac 'sub$LEVEL1/sub$LEVEL2/outline.json'
fac 'final.txt'

# build the full project from scratch;
# the `git clean` command removes all files that have been built from previous test runs
git clean -fd; fac 'outline.json' 
git clean -fd; fac 'sub$LEVEL1/outline.json'
git clean -fd; fac 'sub$LEVEL1/sub$LEVEL2/outline.json'
git clean -fd; fac 'final.txt'
