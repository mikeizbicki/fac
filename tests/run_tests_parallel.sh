#!/bin/bash

# Parallel driver for the golden tests (tests/run_all_tests.sh).
#
# Runs one podman container per (test, variant) pair.  Each container
# gets its own network namespace (so facd can bind 8080 without
# conflicting with siblings), its own PID namespace (so the
# `pkill -f facd` in framework.sh:facd_start only sees its own server),
# and its own writable overlay of the source tree (so .test_output,
# .results/, and the test repo never collide across workers).
#
# The golden test scripts and framework.sh are used unchanged.
# run_all_tests.sh is left as-is and remains the serial ground truth;
# a CI job can run both and diff the sorted failure logs to verify
# behavioural equivalence.
#
# Failure logs are replayed serially, in sorted order, after every
# worker has exited.  The bytes you read when debugging are therefore
# identical to a serial run, regardless of JOBS.

set -u

cd "$(dirname "$0")"

JOBS=${JOBS:-$(nproc)}
IMAGE=${IMAGE:-fac-tests-parallel}

# build the image with the source tree baked in; every `podman run`
# below then gets a fresh writable layer, which is what gives each
# worker its own copy of the repo
podman build -q -t "$IMAGE" .. >/dev/null

# the container's WORKDIR is the repo root (docs/run_tests.sh relies
# on the same assumption); mount coverage underneath it
WORKDIR=$(podman inspect "$IMAGE" --format '{{.Config.WorkingDir}}')
[ -n "$WORKDIR" ] || WORKDIR=/

OUT=$(mktemp -d)
COV="$OUT/cov"
mkdir -p "$COV"
trap 'rm -rf "$OUT"' EXIT

# one worker per (test, variant); the two variants of a test share
# .test_output and .results/ and must not run in the same container
mapfile -t tests < <(ls -d fac*)
specs=()
for t in "${tests[@]}"; do
    specs+=("$t:nogit" "$t:git")
done

run_one() {
    local spec=$1
    local t=${spec%:*} v=${spec##*:}
    local log="$OUT/$t.$v.log"
    local rc="$OUT/$t.$v.rc"

    podman run --rm \
        -v "$COV:$WORKDIR/tests/.coverage" \
        -e NO_COLOR=1 -e TERM=dumb \
        -e FAC_TESTWITHGIT="$([ "$v" = git ] && echo 1)" \
        "$IMAGE" \
        bash -c "cd tests/$t && ./run_test.sh" \
        >"$log" 2>&1
    echo $? >"$rc"
}

# throttle to JOBS concurrent workers
pids=()
i=0
for spec in "${specs[@]}"; do
    run_one "$spec" &
    pids+=($!)
    i=$((i + 1))
    if [ $((i % JOBS)) -eq 0 ]; then
        wait -n || true
    fi
done
for pid in "${pids[@]}"; do
    wait "$pid" || true
done

# deterministic replay: sorted, concatenated, byte-identical to serial
rc=0
while IFS= read -r log; do
    if [ "$(cat "${log%.log}.rc")" -eq 0 ]; then
        continue
    fi
    rc=1
    echo "=== FAIL: $(basename "$log") ==="
    cat "$log"
done < <(find "$OUT" -maxdepth 1 -name '*.log' | sort)

# combine coverage from all workers
if compgen -G "$COV/coverage.*" >/dev/null; then
    (cd "$COV" && python3 -m coverage combine . >/dev/null 2>&1) || true
    (cd "$COV" && python3 -m coverage report) || true
fi

exit $rc
