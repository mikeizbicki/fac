#!/bin/bash
#
# Parallel runner for the fac test suite.
#
# Every test (the doctest pass plus each tests/fac_* submodule) runs in
# its own podman container, which:
#   * gives each test its own network namespace, so the facd tests
#     cannot collide on localhost:8080;
#   * gives each test its own writable copy of the repo, so a crashed
#     test cannot leave git state behind for another test;
#   * never modifies the host working tree.
#
# Tests run JOBS at a time (default: nproc).  Progress is one line per
# event.  On failure the logs of all failing tests are dumped at the
# end in discovery order, so the tail of the output is deterministic.
#
# Env: JOBS (default nproc), IMAGE (default fac-test).

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT=$PWD
LOGDIR=$ROOT/.testlogs
COVERAGE_DIR=$ROOT/.coverage
JOBS=${JOBS:-$(nproc)}
IMAGE=${IMAGE:-fac-test}

# ---------- discovery ----------

tests=(doctest)
for d in tests/fac*; do
    [ -f "$d/run_test.sh" ] && tests+=("$(basename "$d")")
done

echo "discovered ${#tests[@]} tests:"
printf '  %s\n' "${tests[@]}"
echo

# ---------- image ----------

echo "==> building image $IMAGE"
podman build -q -t "$IMAGE" "$ROOT" >/dev/null \
    || { echo "podman build failed" >&2; exit 1; }

rm -rf "$LOGDIR" "$COVERAGE_DIR"
mkdir -p "$LOGDIR" "$COVERAGE_DIR"

# ---------- run one test in a container ----------
#
# The container is given the repo read-only at /repo and the coverage
# directory writable at /coverage.  It copies the repo to /work (so
# submodule git state resolves), redirects tests/.coverage to
# /coverage, and runs the test.
#
# safe.directory is set because inside a rootless container the bind
# mount appears owned by a different uid than the one git runs as.

run_test() {
    local t=$1 inner
    if [ "$t" = doctest ]; then
        inner='cd /work/tests && COVERAGE_FILE=/coverage/coverage.doctest python3 -m coverage run --parallel-mode -m pytest --doctest-modules ../fac'
    else
        inner="cd /work/tests/$t && ./run_test.sh && FAC_TESTWITHGIT=1 ./run_test.sh"
    fi
    podman run --rm \
        -v "$ROOT:/repo:ro" \
        -v "$COVERAGE_DIR:/coverage" \
        "$IMAGE" \
        bash -c "
            set -e
            git config --global --add safe.directory '*'
            git config --global user.name  test
            git config --global user.email test@example.com
            cp -a /repo /work
            rm -rf /work/tests/.coverage
            ln -s /coverage /work/tests/.coverage
            $inner
        "
}

# ---------- parallel scheduler ----------
#
# We keep a plain indexed array of PIDs and a parallel array of names.
# Each test writes its stdout+stderr to $LOGDIR/$t.log and its exit
# code to $LOGDIR/$t.exit; because the subshell that writes the exit
# code is the process we wait on, the file is guaranteed to be written
# by the time reap() runs.

PIDS=()
NAMES=()

launch() {
    local t=$1
    ( run_test "$t" >"$LOGDIR/$t.log" 2>&1
      echo $? >"$LOGDIR/$t.exit" ) &
    PIDS+=("$!")
    NAMES+=("$t")
    printf 'RUN  %s\n' "$t"
}

reap() {
    local pid ec i t rc
    wait -n -p pid
    ec=$?
    t=
    for i in "${!PIDS[@]}"; do
        if [ "${PIDS[$i]}" = "$pid" ]; then
            t=${NAMES[$i]}
            unset 'PIDS[$i]' 'NAMES[$i]'
            break
        fi
    done
    [ -z "$t" ] && return
    rc=$(cat "$LOGDIR/$t.exit" 2>/dev/null || echo "$ec")
    if [ "$rc" = 0 ]; then
        printf 'PASS %s\n' "$t"
    else
        printf 'FAIL %s (exit=%s)  log=.testlogs/%s.log\n' "$t" "$rc" "$t"
    fi
}

for t in "${tests[@]}"; do
    while [ "${#PIDS[@]}" -ge "$JOBS" ]; do reap; done
    launch "$t"
done
while [ "${#PIDS[@]}" -gt 0 ]; do reap; done

# ---------- summary ----------

failed=()
for t in "${tests[@]}"; do
    rc=$(cat "$LOGDIR/$t.exit" 2>/dev/null || echo 1)
    [ "$rc" = 0 ] || failed+=("$t")
done

echo
echo "=== summary ==="
printf 'total:  %d\n' "${#tests[@]}"
printf 'passed: %d\n' "$(( ${#tests[@]} - ${#failed[@]} ))"
printf 'failed: %d\n' "${#failed[@]}"

# ---------- coverage ----------

echo
echo "=== coverage ==="
if [ -n "$(ls -A "$COVERAGE_DIR" 2>/dev/null || true)" ]; then
    (cd "$COVERAGE_DIR" && python3 -m coverage combine && python3 -m coverage report) || true
else
    echo "(no coverage data)"
fi
