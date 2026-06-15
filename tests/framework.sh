# This file should be sourced from the ./run_test.sh script in the test repo.

set -e

####################
# git setup
####################

# Because fac dependency checking relies on git state,
# we must have a clean test repo for the tests to make sense.
if ! [ -z "$(git status --porcelain)" ]; then
    echo 'ERROR: The git repo is not clean (i.e. you may have uncommitted files), but the test script requires a clean repo. You should either commit the files or delete them.'
    exit 1
fi

# tests might be making git commits;
# therefore we need to ensure we are not on a branch
old_branch=$(git symbolic-ref --short -q HEAD || git rev-parse HEAD)
old_commit=$(git rev-parse HEAD)
git -c advice.detachedHead=false checkout "$old_commit"

reset_git() {
    # clean repo to same state as before tests were run;
    # this is used in cleanup at the end,
    # but also inside various test scripts
    git clean -fd -e .results/ -e .test_output
    git checkout .
    git checkout "$old_commit"
}

####################
# test framework code
# ------------------
# We use set -x and PS4 to trace all output of the test script.
# Each call to dotest represents a checkpoint.
# The output of the full run of the test can be very long,
# so when we get a failure (from set -e),
# we want to output only the trace since the last checkpoint.
# We do a lot of fancy IO redirection to make this happen.
# The important end result is:
# 1) $TEST_OUTPUT will contain the trace since the last checkpoint only,
# 2) this should be sufficient to understand/debug the source of the failure.
####################
exec 3>&1 4>&2
TEST_OUTPUT=$(pwd)/.test_output
exec 9>>"$TEST_OUTPUT"
exec >&9 2>&9
export PS4='[${BASH_SOURCE}:${LINENO}] ${FUNCNAME[0]:+${FUNCNAME[0]}(): }'
set -x

on_error() {
    set +x
    local ec=$?
    echo "=== TEST FAILED (exit $ec); dumping $TEST_OUTPUT ===" >&4
    # if facd crashed (e.g. due to an assert),
    # then we want its output in $TEST_OUTPUT;
    # but the output won't be ready for a bit;
    # we could use `wait` to wait for the process to actually stop before printing,
    # but not all errors are due to the process dying,
    # and so we could be waiting indefinitely;
    # we also don't want to manually kill the process
    # because sometimes manually inspecting the process after an error is useful;
    # sleeping provides enough time to ensure that any crash traceback will
    # be printed to $TEST_OUTPUT without risking the script hanging
    sleep 1
    cat "$TEST_OUTPUT" >&4
}
trap on_error ERR

dotest() {
    # takes a checkpoint name as a command line arg;
    # ensures that piped-in stdin matches a known good value
    mkdir -p .results
    cat > .results/"$1"
    diff -u .results/"$1" .expected/"$1"
    echo "=== ${BASH_SOURCE[1]}:${BASH_LINENO[0]} dotest succeeded: $1  ===" >&4

    # truncate $TEST_OUTPUT
    # (so that the trace before passing checkpoint is deleted)
    exec 9>"$TEST_OUTPUT"
    exec >&9 2>&9
}

####################
# fac config
####################

# Asserting invariants is slow and disabled by default.
# We enable it for tests.
export FAC_DO_ASSERT_INVARIANTS=True

# the default is not making git commits after each invocation;
# specifying this var enables git commits;
# tests should always get the same output either way
fac_params=''
if [ -z "$FAC_TESTWITHGIT" ]; then
    fac_params=' --no-auto_commit'
else
    fac_params=' --allow_dirty'
fi

# we override the fac build command with a command that tracks code coverage
shopt -s expand_aliases
COVERAGE_DIR=$(dirname "${BASH_SOURCE[0]}")/.coverage
COVERAGE_PATH="$COVERAGE_DIR"/"$(basename "$(pwd)")"
mkdir -p "$COVERAGE_DIR"
alias fac="python3 -m coverage run --parallel-mode --source=fac --data-file=$COVERAGE_PATH -m fac $fac_params"
alias facd="python3 -m coverage run --parallel-mode --source=fac --data-file=$COVERAGE_PATH -m facd --loglevel=TRACE $fac_params"

facd_HOST=localhost:8080
facd_TIMEOUT=20
facd_start() {
    echo "=== starting facd ===" >&4
    # ensure there are no other servers running;
    # this complex regex should match a plain invocation of facd
    # or the invocation using coverage in the alias above
    pattern='(^|/)facd( |$)|[-]m facd'
    for _ in $(seq 1 50); do
        pkill -f "$pattern" || true
        pgrep -f "$pattern" >/dev/null || break
        sleep 0.1
    done
    if pgrep -f "$pattern" >/dev/null; then
        return 1
    fi

    # start the server
    facd &
    facd_pid=$!

    # ensure the webserver is running
    for i in $(seq 1 $facd_TIMEOUT); do
      sleep 1

      # if facd proc not running, fail
      kill -0 "$facd_pid" 2>/dev/null || return 1
      
      # if web interface not responding, wait
      response=$(curl -s "$facd_HOST"/job_states) && { break; }
    done

    echo "=== facd started ===" >&4
}

finalize_tests() {
    echo "=== finalizing ===" >&4

    # close "$TEST_OUTPUT"
    exec 9>&-

    # restore original git state
    reset_git
    git checkout "$old_branch"

    # ensure facd has stopped if it was started
    if [ -n "$facd_pid" ]; then
        kill "$facd_pid"

        # wait 5 sec for process to terminate gracefully;
        # otherwise force kill and fail tests
        for _ in $(seq 1 50); do
            kill -0 "$facd_pid" 2>/dev/null || break
            sleep 0.1
        done
        if kill -0 "$facd_pid" 2>/dev/null; then
            echo "=== facd force killed ===" >&4
            kill -KILL "$facd_pid"
            wait "$facd_pid" 2>/dev/null
            return 1
        fi
    fi

    echo "=== finalized ===" >&4
}

facd_wait() {
    # Because facd is running as a background process,
    # control flow will be returned to the test scripts before
    # the build system has finished its work.
    # This function waits until facd has finished all its work.
    sleep 1
    for i in $(seq 1 $facd_TIMEOUT ); do
      sleep 1
      # We check that facd is finished by ensuring there are no running jobs
      # and no contexts in a non-finalized state.
      # In theory, both of these checks shouldn't be needed,
      # but we add them both to ensure that the test framework is robust
      # to any bugs in these systems.
      # We also wait a bit longer than needed,
      # which slows the test scripts down,
      # but again makes them more robust.
      response1=$(curl -s "$facd_HOST"/job_states) || return 1
      response2=$(curl -s "$facd_HOST"/context_states) || return 1
      counts=$(jq -n \
        --argjson js "$response1" \
        --argjson cs "$response2" \
        '[$js.queued, $js.running, $cs.unresolved, $cs.waiting, $cs.buildable, $cs.build_required] | map(length) | add')
      if [ "$counts" -eq 0 ]; then
        return 0
      fi

      echo "facd_wait; i=$i"
    done
    echo "facd_wait() exceeded TIMEOUT=$facd_TIMEOUT"
    return 1
}

facd_add_target() {
    curl -sX POST "http://$facd_HOST/add_target" -H "Content-Type: application/json" -d "{\"target\":\"$1\"}" -w '\n'
}

facd_context_states() {
    facd_wait
    curl -s "http://$facd_HOST/context_states" | jq
}
