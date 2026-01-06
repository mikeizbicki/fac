#!/bin/bash

# Purpose: Execute Cram tests in an isolated Docker environment
#
# ISOLATION RATIONALE:
# This script runs Cram tests inside a Docker container to provide complete
# isolation from the host system. This isolation serves several critical purposes:
#
# 1. SAFETY: Test commands cannot accidentally modify, delete, or corrupt files
#    on the host system. This is especially important when testing build tools
#    that may create/modify files or when documenting potentially destructive commands.
#
# 2. REPEATABILITY: Each test run starts with a clean, identical environment.
#    No leftover files, environment variables, or system state from previous
#    runs can affect the current test, ensuring consistent results.
#
# 3. SANDBOX TESTING: Commands in documentation can be safely tested without
#    worrying about side effects. This allows testing of commands that might
#    otherwise be dangerous to run on a development machine.
#
# 4. CI/CD COMPATIBILITY: The isolated nature makes these tests suitable for
#    automated CI/CD pipelines where host system contamination is unacceptable.
#
# The script copies the test file INTO the container rather than using bind
# mounts, ensuring true isolation - nothing the container does can affect the host.

set -ex

if [ $# -eq 0 ]; then
    echo "Usage: $0 <cram-test-file>"
    echo "Example: $0 documentation-test.t"
    echo ""
    echo "Runs the specified Cram test in an isolated Docker container"
    echo "for safety and repeatability."
    exit 1
fi

TEST_FILE="$1"

if [ ! -f "$TEST_FILE" ]; then
    echo "Error: Test file '$TEST_FILE' not found"
    exit 1
fi

TEST_BASENAME=$(basename "$TEST_FILE")

# Build the Docker image from the local Dockerfile
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker build -t cram-test-local "$SCRIPT_DIR"

# Execute test in isolated container
# - No bind mounts to prevent host file system access
# - File is copied in via stdin to maintain isolation
# - Container is automatically destroyed after execution
docker run --rm -i \
    cram-test \
    bash -c "
        # Copy test file into container workspace
        # Note that cat receives the input from stdin here
        cat > /workspace/$TEST_BASENAME
        cd /workspace

        # Run the Cram test
        cram $TEST_BASENAME
    " < "$TEST_FILE"
