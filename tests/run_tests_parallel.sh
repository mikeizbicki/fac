#!/bin/bash
# tests/run_tests_parallel.sh
#
# Parallel variant of run_all_tests.sh.
#
# Each test case (doctests plus each tests/fac_* submodule, once per env
# variant) runs inside its own podman container.  Isolation is what makes
# parallelism safe here:
#
#   * netns  -- facd binds localhost:8080 and framework.sh pkills any
#               running facd, so two tests on one netns would fight.
#   * MNT    -- framework.sh mutates git state via reset_git.
#   * coverage -- each container writes its own data file under
#                 tests/.coverage; combined on the host at the end.
#
# The repo is mounted RO and copied into the container, so a crashed build
# cannot leave the working tree dirty.  Failing test logs are dumped at the
# end in discovery order, so the tail of the output is deterministic
# regardless of scheduling.
#
# Env:
#   JOBS=N     number of parallel containers
#              (default: min(nproc, RAM_MB/400))
#   IMAGE=tag  podman image tag to use (default: fac-test)
#   NO_COLOR   disables ANSI colors

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"
REPO_ROOT=$(dirname "$SCRIPT_DIR")

NPROC=$(nproc)
RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
RAM_JOBS=$((RAM_MB / 400))
[ "$RAM_JOBS" -lt 1 ] && RAM_JOBS=1
[ "$RAM_JOBS" -gt "$NPROC" ] && RAM_JOBS=$NPROC
JOBS=${JOBS:-$RAM_JOBS}
IMAGE=${IMAGE:-fac-test}

COVERAGE_DIR=$SCRIPT_DIR/.coverage
LOGDIR=$SCRIPT_DIR/.testlogs
rm -rf "$COVERAGE_DIR" "$LOGDIR"
mkdir -p "$COVERAGE_DIR" "$LOGDIR"

# ---------------- discovery ----------------
declare -a ALL_IDS=()
ALL_IDS+=("doctest")
for test in fac*; do
    [ -d "$test" ] && [ -f "$test/run_test.sh" ] || continue
    ALL_IDS+=("$test")
done
TOTAL=${#ALL_IDS[@]}

# ---------------- tty / color ----------------
USE_TTY=0; [ -t 1 ] && USE_TTY=1
USE_COLOR=0
[ "$USE_TTY" = 1 ] && [ -z "${NO_COLOR:-}" ] && USE_COLOR=1
c_green=$'\033[32m'; c_red=$'\033[31m'; c_reset=$'\033[0m'

# ---------------- state ----------------
declare -A STATE=() START_TIME=()
for id in "${ALL_IDS[@]}"; do STATE[$id]=pending; done
declare -A PID_OF=()
running=0
START_EPOCH=$SECONDS

STATUS_LINE="[0/$TOTAL] starting..."
update_status_line() {
    local n_pass=0 n_fail=0 n_pend=0 n_run=0 rl=""
    for id in "${ALL_IDS[@]}"; do
        case "${STATE[$id]}" in
            running) n_run=$((n_run+1)); [ -n "$rl" ] && rl="$rl $id" || rl=$id ;;
            pass)    n_pass=$((n_pass+1)) ;;
            fail)    n_fail=$((n_fail+1)) ;;
            *)       n_pend=$((n_pend+1)) ;;
        esac
    done
    local done=$((n_pass+n_fail))
    local el=$((SECONDS-START_EPOCH))
    [ -n "$rl" ] && [ ${#rl} -gt 70 ] && rl="${rl:0:67}..."
    local tail=""; [ -n "$rl" ] && tail=" | run: $rl"
    STATUS_LINE="[$done/$TOTAL] pass=$n_pass fail=$n_fail pend=$n_pend ${el}s${tail}"
}

emit_event() {
    # Scroll an event above the bottom status line.
    if [ "$USE_TTY" = 1 ]; then
        printf '\033[1A\r\033[K%s\n' "$1"
    else
        printf '%s\n' "$1"
    fi
    update_status_line
    [ "$USE_TTY" = 1 ] && printf '%s\n' "$STATUS_LINE"
}

if [ "$USE_TTY" = 1 ]; then printf '%s\n' "$STATUS_LINE"; fi

# ---------------- build image ----------------
if ! podman image exists "$IMAGE"; then
    emit_event "BUILD podman image $IMAGE"
    if ! podman build -t "$IMAGE" -f "$REPO_ROOT/Dockerfile" "$REPO_ROOT" \
            >"$LOGDIR/.image_build.log" 2>&1; then
        emit_event "FAIL image build (see .testlogs/.image_build.log)"
        [ "$USE_TTY" = 1 ] && printf '\033[1A\r\033[K'
        cat "$LOGDIR/.image_build.log"
        exit 1
    fi
    emit_event "DONE  podman image $IMAGE"
fi

# ---------------- worker ----------------
# Common podman flags: no network (deterministic tests never call a model),
# repo mounted RO, coverage dir mounted RW, and a live copy inside the
# container so that framework.sh's reset_git cannot touch the host tree.
podman_run() {
    local id=$1 covname=$2 script=$3
    podman run --rm --network=none \
        -v "$REPO_ROOT:/repo:ro" \
        -v "$COVERAGE_DIR:/coverage" \
        -e NO_COLOR=1 -e TERM=dumb \
        -e COVERAGE_FILE=/coverage/coverage.$covname \
        "$IMAGE" \
        bash -c "$script"
}

run_one() {
    local id=$1
    if [ "$id" = doctest ]; then
        podman_run "$id" "$id" '
            set -e
            cp -a /repo /work
            cd /work
            python3 -m coverage run --parallel-mode -m pytest --doctest-modules fac
        '
        return
    fi
    podman_run "$id" "$id" "
        set -e
        cp -a /repo /work
        cd /work/tests/$id
        echo '########## env: <none> ##########'
        ./run_test.sh
        echo '########## env: FAC_TESTWITHGIT=1 ##########'
        FAC_TESTWITHGIT=1 ./run_test.sh
    "
}

launch() {
    local id=$1
    STATE[$id]=running
    START_TIME[$id]=$SECONDS
    ( run_one "$id" ) >"$LOGDIR/$id.log" 2>&1 &
    PID_OF[$!]=$id
    running=$((running+1))
    emit_event "RUN  $id"
}

reap() {
    local pid ec
    wait -n -p pid
    ec=$?
    local id=${PID_OF[$pid]:-}
    [ -z "$id" ] && return
    unset 'PID_OF[$pid]'
    running=$((running-1))
    local dur=$((SECONDS-START_TIME[$id]))
    if [ "$ec" -eq 0 ]; then
        STATE[$id]=pass
        if [ "$USE_COLOR" = 1 ]; then emit_event "${c_green}PASS${c_reset} $id (${dur}s)"
        else emit_event "PASS $id (${dur}s)"; fi
    else
        STATE[$id]=fail
        if [ "$USE_COLOR" = 1 ]; then
            emit_event "${c_red}FAIL${c_reset} $id (${dur}s, ec=$ec) -> .testlogs/$id.log"
        else
            emit_event "FAIL $id (${dur}s, ec=$ec) -> .testlogs/$id.log"
        fi
    fi
}

# ---------------- scheduler ----------------
for id in "${ALL_IDS[@]}"; do
    while [ "$running" -ge "$JOBS" ]; do reap; done
    launch "$id"
done
while [ "$running" -gt 0 ]; do reap; done

# ---------------- final report ----------------
if [ "$USE_TTY" = 1 ]; then printf '\033[1A\r\033[K'; fi

n_pass=0; n_fail=0
declare -a failed_ids=()
for id in "${ALL_IDS[@]}"; do
    case "${STATE[$id]}" in
        pass) n_pass=$((n_pass+1)) ;;
        fail) n_fail=$((n_fail+1)); failed_ids+=("$id") ;;
    esac
done

printf '\n=== summary ===\n'
printf 'total:  %d\n' "$TOTAL"
printf 'passed: %d\n' "$n_pass"
printf 'failed: %d\n' "$n_fail"
if [ "${#failed_ids[@]}" -gt 0 ]; then
    printf 'failing test cases (in discovery order):\n'
    for id in "${failed_ids[@]}"; do printf '  - %s\n' "$id"; done
fi

printf '\n=== coverage ===\n'
(
    cd "$COVERAGE_DIR"
    shopt -s nullglob
