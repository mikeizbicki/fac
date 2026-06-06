# Testing

fac is a complicated tool, and so testing is important for ensuring that systems work correctly.

## doctests

Complex code should be factored into pure (side-effect free, no IO)
and non-pure components.
Pure functions always have extensive doctests
and should be located in the `fac/util/` folder.

## asserts

Every class contains an `assert_invariants` method that:
1. is called at regular intervals to ensure invariants are maintained
2. never performs IO

Many invariant checks can be slow, but we still prefer to include them.
If invariants cannot be practicably written,
then a comment should still be added explaining the invariant and why the check cannot be written.

Some classes optionally contain additional invariant checking methods.
These methods can perform IO if needed.

## custom golden tests

fac has complex interactions with git that make standard testing frameworks inconvenient for end-to-end tests.
Therefore, we have created our own custom testing framework.

Each subfolder in `tests/` is a submodule that contains a set of tests.
The folder must contain the following files:
1. `fac.yaml` which defines the targets for the test
2. `.expected/` which contains the expected output for various checkpoints defined in `run_test.sh`
3. `run_test.sh` which actually performs the check
    1. If this script exits with a 0 status, the test passes
