#!/bin/bash

set -e

# this script runs all test cases and outputs a code coverage report

COVERAGE_DIR=$(dirname "${BASH_SOURCE[0]}")/.coverage
rm -rf "$COVERAGE_DIR"

# run doctests
COVERAGE_FILE="$COVERAGE_DIR/coverage.doctest" \
  python3 -m coverage run --parallel-mode -m pytest --doctest-modules ../fac

# run golden tests
for test in fac*; do
    for env in "" "FAC_TESTWITHGIT=1"; do
        echo '----------------------------------------'
        echo "test: $test env: $env"
        echo '----------------------------------------'
        (cd "$test" && env $env ./run_test.sh)
    done
done

cd "$COVERAGE_DIR"
python3 -m coverage combine *
python3 -m coverage report
