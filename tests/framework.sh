# This file should be sourced from the ./run_test.sh script in the test repo.

# Because fac dependency checking relies on git state,
# we must have a clean repo for the tests to make sense.
if ! [ -z "$(git status --porcelain)" ]; then
    echo 'ERROR: The git repo is not clean (i.e. you may have uncommitted files), but the test script requires a clean repo. You should either commit the files or delete them.'
    echo 'HINT: You can delete all uncommitted files with the `git clean -fd` command.'
    exit 1
fi

# Asserting invariants is slow and disable by default.
# We enable it for our tests.
export FAC_DO_ASSERT_INVARIANTS=True

# We use set -x and PS4 to trace all output of the test script.
# Each call to dotest represents a checkpoint.
# The test script will abort when any command errors,
# and if we abort then $TEST_OUTPUT will contain the trace since the last checkpoint only.
exec 3>&1 4>&2
TEST_OUTPUT=$(pwd)/.test_output
exec 9>>"$TEST_OUTPUT"
exec >&9 2>&9
export PS4='[${BASH_SOURCE}:${LINENO}] ${FUNCNAME[0]:+${FUNCNAME[0]}(): }'
on_error() {
    set +x
    local ec=$?
    echo "=== TEST FAILED (exit $ec); dumping $TEST_OUTPUT ===" >&4
    cat "$TEST_OUTPUT" >&4
}
trap on_error ERR
set -ex

dotest() {
    # takes a checkpoint name as a command line arg;
    # ensures that piped-in stdin matches a known good value
    mkdir -p .results
    cat > .results/"$1"
    diff -u .results/"$1" .expected/"$1"
    echo "=== ${BASH_SOURCE[1]}:${BASH_LINENO[0]} dotest succeeded: $1  ===" >&4

    # truncate $TEST_OUTPUT
    exec 9>"$TEST_OUTPUT"
    exec >&9 2>&9
}

# fac has many different modes that it can be run in;
# these modes have different runtime characteristics but they should always
# result in the same build files and so should pass the same tests;
# the caller can use environment variables to set which mode will be used
shopt -s expand_aliases
if [ -n "$FAC_TESTWITHGIT" ]; then
    alias fac='python3 -m fac'
else
    alias fac='python3 -m fac --auto_commit=False'
fi

# tests might be making git commits;
# therefore we need to ensure we are not on a branch
old_branch=$(git symbolic-ref --short -q HEAD || git rev-parse HEAD)
old_commit=$(git rev-parse HEAD)
git checkout "$old_commit"

reset_git() {
    # clean repo to same state as before tests were run;
    # this is used in cleanup at the end,
    # but also inside various test scripts
    git clean -fd -e .results/
    git checkout .
    git checkout "$old_commit"
}

finalize_tests() {
    # close "$TEST_OUTPUT"
    exec 9>&-

    # restore original git state
    reset_git
    git checkout "$old_branch"

    # ensure facd has stopped if it was started
    killall facd || true
}

facd_HOST=localhost:8080
facd_TIMEOUT=20
facd_start() {
    echo "=== starting facd ===" >&4
    # ensure there are no other servers running, then start the server
    killall facd || true
    facd --auto_commit=False &

    # ensure the webserver is running
    for i in $(seq 1 $facd_TIMEOUT); do
      sleep 1

      # if facd proc not running, fail
      ps | grep facd || return 1
      
      # if web interface not responding, wait
      response=$(curl -s "$facd_HOST"/job_states) && { break; }
    done

    echo "=== facd started ===" >&4
}

facd_wait() {
    # wait until facd is in a "stable" state where all jobs have finished;
    # this is needed to:
    # 1. ensure that facd has had a chance to register changes to files
    # 2. ensure that any build steps have finished
    # fac tests do not need to call this function because fac blocks until finished
    for i in $(seq 1 $facd_TIMEOUT); do
      sleep 1
      response=$(curl -s "$facd_HOST"/job_states) || { return 1; }
      queued=$(echo "$response" | jq '.queued | length')
      running=$(echo "$response" | jq '.running | length')
      if [ "$queued" -eq 0 ] && [ "$running" -eq 0 ]; then
        return 0
      fi
      echo "facd_wait; i=$i"
    done
    echo "facd_wait() exceeded TIMEOUT=$facd_TIMEOUT"
    return 1
}

facd_add_target() {
    curl -X POST "http://$facd_HOST/add_target" -H "Content-Type: application/json" -d "{\"target\":\"$1\"}"
}
