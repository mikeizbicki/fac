# Error message reference

This file is both a byexample test and the readable reference for what
fac's error messages look like.  Every scenario runs a real `fac`
command in a fresh git repo and shows the output verbatim.

To run:

    byexample -l shell docs/error_messages.md

To regenerate the expected output after an intentional change to a
message:

    byexample --update -l shell docs/error_messages.md

fac splits errors into two categories, distinguished by exit code:

- **exit code 1**: a `UserError` -- a problem in the user's `fac.yaml`,
  a template, a script, or an LLM call.  Rendered as a compiler-style
  diagnostic (message, source frames, context, hint) with no Python
  traceback.
- **exit code 2**: an `InternalError` -- a bug in fac itself, or an
  unexpected exception.  Rendered with the full Python traceback so
  the bug can be diagnosed.

The `|| echo "exit code: $?"` idiom used below surfaces the exit code
without turning the non-zero exit into a byexample failure.

## Setup

A helper so each scenario does not repeat the git boilerplate:

```bash
$ setup_repo() {
>     cd $(mktemp -d)
>     git init -q
>     echo .fac.log > .gitignore
>     git add .gitignore
>     git commit -qm init
> }
```

## Unknown key in a scope

A scope is a top-level YAML entry whose name ends in `/`.  Only a
fixed set of keys is valid inside a scope; any other key is reported
along with the scope name so the user can see where the typo is.

```bash
$ setup_repo
$ cat > fac.yaml <<'EOF'
> example/:
>   targts:
>     foo.txt:
>       cmd: echo hi > foo.txt
> EOF
$ git add fac.yaml
$ git commit -qm 'create fac.yaml'
$ fac foo.txt || echo "exit code: $?"
[ERROR] error reading fac.yaml; key="targts" invalid
[ERROR] scope: example/
[ERROR]   hint: perhaps this should be within a targets: dictionary?
exit code: 1
```

## A dependency that does not match any target

A dependency listed in `dependencies:` must match one of the targets
declared in the same `fac.yaml` (or be marked `in_fac.yaml: false`).
If it matches nothing, fac reports the target and the dependency so
the user can find the typo.

```bash
$ setup_repo
$ cat > fac.yaml <<'EOF'
> foo.txt:
>   cmd: echo hi > foo.txt
>   dependencies:
>   - does-not-exist.json
> EOF
$ git add fac.yaml
$ git commit -qm 'create fac.yaml'
$ fac foo.txt || echo "exit code: $?"
[ERROR] 1 errors found in fac.yaml
[ERROR]   at fac.yaml:4
[ERROR]   errors:
[ERROR] <...>
exit code: 1
```

## A variable whose shell command fails

Variables are evaluated in a `bash` subshell.  When the command exits
non-zero, fac reports the variable and the target it was being
evaluated for, and (when it can recognize the error) a hint about
which dependency would build the missing file.

```bash
$ setup_repo
$ cat > fac.yaml <<'EOF'
> foo.txt:
>   cmd: echo hi > foo.txt
>   variables:
>     X: ls does-not-exist.json
> EOF
$ git add fac.yaml
$ git commit -qm 'create fac.yaml'
$ fac foo.txt || echo "exit code: $?"
[ERROR] failed evaluating variable X in target foo.txt
[ERROR]   at <unknown> (X): foo.txt
[ERROR] <...>
exit code: 1
```
