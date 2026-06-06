#!/bin/bash

set -ex
for test in fac_test*; do
    reset
    echo '----------------------------------------'
    echo "test=$test"
    echo '----------------------------------------'
    cd $test
    ./run_test.sh
    cd ..
done
