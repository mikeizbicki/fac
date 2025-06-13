#!/bin/sh

set -ex

# incremental building
./fac test_project 'outline.json' 
./fac test_project 'sub$LEVEL1/outline.json'
./fac test_project 'sub$LEVEL1/sub$LEVEL2/outline.json'
./fac test_project 'final.txt'

# build the full project from scratch;
# the `git clean` command removes all files that have been built from previous test runs
cd test_project; git clean -fd; cd -; ./fac test_project 'outline.json' 
cd test_project; git clean -fd; cd -; ./fac test_project 'sub$LEVEL1/outline.json'
cd test_project; git clean -fd; cd -; ./fac test_project 'sub$LEVEL1/sub$LEVEL2/outline.json'
cd test_project; git clean -fd; cd -; ./fac test_project 'final.txt'
