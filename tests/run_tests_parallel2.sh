#!/bin/bash
#
# Parallel test runner for the fac test suite.
#
# Like tests/run_all_tests.sh, but:
#   * each test runs in its own podman container, so the facd tests
#     cannot collide on localhost:8080 and a crashed test cannot leave
#     git state behind that affects another test;
#   * tests run concurrently (JOBS at a time);
#   * progress is printed one line per event (RUN / PASS / FAIL);
#   * on failure, the log of each failing test is dumped at the end in
#     discovery order, so the tail of the output is deterministic.
#
# The container bind-mounts the repo read-only and copies it to a
# writable location before running the test, so submodule git state
# (tests/<sub>/.git -> ../../.git/modules/...) resolves correctly and
# the host working tree is never modified.
#
# Env:
#   JOBS   maximum number of concurrent containers (default: nproc)
#   IMAGE  container image tag (default: fac-test)

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

REPO_DIR=$(pwd)/..
LOGDIR=$(pwd)/.testlogs
COVERAGE_DIR=$(pwd)/.coverage

JOBS=${JOBS:-$(nproc)}
IMAGE=${IMAGE:-fac-test}

# ---------- discovery ----------

tests=(doctest)
for d in fac*; do
    [ -d "$d" ] && [ -f "$d/run_test.sh" ] && tests+=("$d")
done

# ---------- image ----------

rm -rf "$LOGDIR"
mkdir -p "$LOGDIR" "$COVERAGE_DIR"

echo "==> building image $IMAGE"
podman build -q -t "$IMAGE" "$REPO_DIR" >/dev/null \
    || { echo "podman build failed" >&2; exit 1; }

# ---------- container command ----------

# Prints the bash command that runs test $1 inside the container.
container_cmd_for() {
    case "$1" in
        doctest)
            echo 'cd /work/tests && COVERAGE_FILE=/coverage/coverage.doctest python3 -m coverage run --parallel-mode -m pytest --doctest-modules ../fac'
            ;;
        *)
            echo "cd /work/tests/$1 && ./run_test.sh && FAC_TESTWITHGIT=1 ./run_test.sh"
            ;;
    esac
}

# ---------- scheduler ----------

declare -A STATE START_OF PID_OF
declare -i N_PASS=0 N_FAIL=0

launch() {
    local t=$1 inner
    inner=$(container_cmd_for "$t")
    STATE[$t]=running
    START_OF[$t]=$SECONDS
    podman run --rm \
        -e GIT_AUTHOR_NAME=test \
        -e GIT_AUTHOR_EMAIL=test@example.com \
        -e GIT_COMMITTER_NAME=test \
        -e GIT_COMMITTER_EMAIL=test@example.com \
        -v "$REPO_DIR:/repo:ro" \
        -v "$COVERAGE_DIR:/coverage" \
        "$IMAGE" \
        bash -c "cp -a /repo /work && rm -rf /work/tests/.coverage && ln -s /coverage /work/tests/.coverage && $inner" \
        >"$LOGDIR/$t.log" 2>&1 &
    PID_OF[$!]=$t
    echo "RUN  $t"
}

reap_one() {
    local p ec t dur
    wait -n -p p
    ec=$?
    t=${PID_OF[$p]}
    unset 'PID_OF[$p]'
    dur=$((SECONDS - START_OF[$t]))
    if [ "$ec" -eq 0 ]; then
        STATE[$t]=passed
        N_PASS+=1
        echo "PASS $t (${dur}s)"
    else
        STATE[$t]=failed
        N_FAIL+=1
        echo "FAIL $t (${dur}s, exit=$ec)  log=.testlogs/$t.log"
    fi
}

for t in "${tests[@]}"; do
    while [ "${#PID_OF[@]}" -ge "$JOBS" ]; do reap_one; done
    launch "$t"
done
while [ "${#PID_OF[@]}" -gt 0 ]; do reap_one; done

# ---------- summary ----------

echo
echo "=== summary ==="
echo "total:  ${#tests[@]}"
echo "passed: $N_PASS"
echo "failed: $N_FAIL"

if [ "$N_FAIL" -gt 0 ]; then
    echo
    echo "=== failing logs (in discovery order) ==="
    for t in "${tests[@]}"; do
        if [ "${STATE[$t]}" = failed ]; then
            echo
            echo "----- $t -----"
            cat "$LOGDIR/$t.log"
            echo "----- end $t -----"
        fi
    done
    exit 1
fi

# ---------- coverage ----------

echo
echo "=== coverage ==="
if [ -n "$(ls -A "$COVERAGE_DIR" 2>/dev/null || true)" ]; then
    (cd "$COVERAGE_DIR" && python3 -m coverage combine && python3 -m coverage report) || true
else
    echo "(no coverage data)"
fi
