# Basic fac Tutorial

`fac` is a build system designed for automating AI workflows.
It works with all AI providers (e.g. GPT, Claude, Gemeni, Deepseek, Qwen) and all modalities (e.g. text, image, video, audio).

In this tutorial, we will create a pipeline for generating a college senior thesis using AI.

**What is a build system?**

A *build system* is a tool that converts a project's source code into something we can actually run.
For most programming languages, a *compiler* processes a single file;
then the build system calls the compiler on files in the many project files in the right order.
For example in the python world, `python` is the "compiler" and `pip` is the "build system".
In fac, the model is the "compiler" and `fac` is the "build system".
Our project source code is "human readable prompts",
the AIs compile these prompts into different output types,
and `fac` calls the AIs in the appropriate order automatically including the prompts from previous calls.

| language  | compiler          | build system config   | build system command  |
| --------- | ----------------- | --------------------- | --------------------- |
| python    | `python`          | `pyproject.toml`      | `pip`                 |
| C         | `gcc`             | `Makefile`            | `make`                |
| docker    | `docker build`    | `docker-compose.yaml` | `docker compose`      |
| English   | AI                | `fac.yaml`            | `fac`                 |

**Why call it fac?**

The word "fac" is Latin for "make".
[Make](https://en.wikipedia.org/wiki/Make_(software\)) was the first build system and remains widely used to develop C programs:
the linux kernel, CPython, R, and llama.cpp projects all all built by running `make`.
The name fac was chosen because the "right way" to think about AI is as a mischievous little demon that is always subtly trying to do evil,
and these demons are traditionally commanded via [latin spells](https://en.wikipedia.org/wiki/Doctor_Faustus_(play)).
All commands in the fac-suite are Latin-based to help remind us of [the shoggoth behind the chat](https://en.wikipedia.org/wiki/Shoggoth#In_popular_culture)).

## Project Setup

All fac projects must be in a git repo,
so we start by creating the repo.

```bash
$ cd $(mktemp -d)
$ git init
<...>
```

> **NOTE:**
> This tutorial is fully reproducible and tested using [byexample](https://byexamples.github.io/byexample/).
> `byexample` tests markdown code by running the code in the code blocks and verifying that the output exactly matches output provided.
> The `<...>` output line denotes that the output will not actually be displayed/checked in byexample because it is "unimportant" (possibly nondeterministic, very large, etc).

We will also need to setup the gitignore for fac:
```bash
$ echo .fac.log > .gitignore
$ git add .gitignore
$ git commit -m 'add gitignore'
<...>
```

## Deterministic `fac.yaml`

Now we create a simple `fac.yaml` file,
which controls how `fac` will build the project.

```bash
$ cat > fac.yaml <<'EOF'
> outline.json:
>   cmd: |
>     echo '{"topic1_food": "This section will describe the traditional foods and cooking techniques of the region.", "topic2_culture": "This section will describe the social customs and cultural rituals preserved across generations."}' > outline.json
>
> page/$TOPIC/about.md:
>   cmd: |
>     jq -r ".$TOPIC" outline.json > page/$TOPIC/about.md
>   dependencies:
>   - outline.json
>   variables:
>     TOPIC: |
>       jq -r 'keys[]' outline.json
>
> final.txt:
>   cmd: |
>     echo "College Thesis" > final.txt
>     for f in page/*/about.md; do
>       echo "" >> final.txt
>       echo "## $f" >> final.txt
>       echo "" >> final.txt
>       cat "$f" >> final.txt
>     done
>   dependencies:
>   - page/$TOPIC/about.md
> EOF
```

> **NOTE:**
> The `>` leaders for the heardoc are required for byexample.
> They unfortunately make copy/paste more awkward :(

The top level entries in `fac.yaml` define the *targets*,
which are the files that can be built with `fac`.
The file above has two targets `outline.json` and `page/$TOPIC/about.md`.
We will see how these work shortly.

To build targets, we must have a clean repo.
So every time we modify the `fac.yaml` (or any other file), we must commit it.

```bash
$ git add fac.yaml
$ git commit -m 'create fac.yaml'
<...>
```

Recall that we can always use `git ls-files` to view which files git knows about.
The tutorial will do this heavily both for your understanding and for the byexample test cases.
```bash
$ git ls-files
.gitignore
fac.yaml
```

### Basic build syntax

Now we are ready to build with the `fac` command.
```bash
$ fac outline.json
<...>
```

You can see that this command created the `outline.js` file for us by running the `cmd` field in the `fac.yaml`.
Also observe that a post-processing step reformatted the JSON for us.
```bash
$ cat outline.json
{
    "topic1_food": "This section will describe the traditional foods and cooking techniques of the region.",
    "topic2_culture": "This section will describe the social customs and cultural rituals preserved across generations."
}
```

`fac` also automatically committed these changes for us into the repo.
```bash
$ git log --oneline
<...> (HEAD -> master) [bot] fac outline.json
<...> create fac.yaml
<...> add gitignore
```

It also generated a handful of hidden files for us that track properties about each of the files in the repo that have been built with `fac`.
```
$ git ls-files
.buildlog
.gitignore
.outline.json.buildlog
.outline.json.facjson
fac.yaml
outline.json
```
The `.*.buildlog` and `.*.facjson` files have semantic meaning and are intended to be tracked/distributed with the repo, so they should not be added to `.gitignore`.

One reason for automatically tracking these changes via git is so that we can easily undo them.
The standard git command below undoes the previous commit:
```
$ git reset --hard HEAD~1
HEAD is now at <...> create fac.yaml
```

Now our repo has been reset to before the `fac` command:
```
$ git log --oneline
<...> (HEAD -> master) create fac.yaml
<...> add gitignore
$ git ls-files
.gitignore
fac.yaml
```

### More complex build

The `page/$TOPIC/about.md` target is much more interesting than `outline.json` for two reasons.

1. There is a variable `TOPIC` inside the target that allows the target to build multiple files.

    This variable will be expanded by first running the command in the `variables['TOPIC']` entry.
    The output will be split on newlines and each resulting line will create a new "expanded target".

1. The target contains a `dependencies` list inside of it,
    and all of these dependencies will be built for us automatically when we build `page/$TOPIC/about.md`.

Let's see this in action:

```bash
$ fac 'page/$TOPIC/about.md'
<...>
```

`fac` first built `outline.json` (as a dependency), then evaluated the `TOPIC` variable.
The command `jq -r 'keys[]' outline.json` produced the text

```bash
$ jq -r 'keys[]' outline.json
topic1_food
topic2_culture
```

Since the variable contains a newline, `fac` split the output into two values and created two "expanded" targets, one for each value:
`page/topic1_food/about.md` and `page/topic2_culture/about.md`.
It then ran the same `cmd` once per expanded target, with `$TOPIC` set to the corresponding value each time.
This is how a single entry in `fac.yaml` can build multiple files.

We can see that `outline.json` was built automatically, before the `page/...` files:

```bash
$ git ls-files | grep -v '/\.\|^\.' # the grep removes hidden files
fac.yaml
outline.json
page/topic1_food/about.md
page/topic2_culture/about.md
```

And each generated file contains the value of `$TOPIC` that was used to build it.

```bash
$ cat page/topic1_food/about.md
This section will describe the traditional foods and cooking techniques of the region.
$ cat page/topic2_culture/about.md
This section will describe the social customs and cultural rituals preserved across generations.
```

Each `page/.../about.md` file contains the *value* (not the key) from
`outline.json`, because the `cmd` uses `jq -r ".$TOPIC" outline.json`
to look up the value for the current key.
This will make it easy to see what has changed when we modify `outline.json` later.

#### Variables

Variables are evaluated in a `bash` subshell, so any command that works in a shell can be used as a variable definition.
Standard Unix tools (`jq`, `ls`, `find`, `echo`, `cat`) are the natural way to generate the value of a variable,
and they are the most common thing to find in the `variables` section of a real `fac.yaml`.

The output of the command is processed as follows before it becomes the variable value:

1. The output is stripped and split on newlines.
    Each resulting line is one value.
    (This is why `jq -r` — "raw output" — is the standard idiom: without `-r`, `jq` emits multi-line JSON and the variable would be split at the wrong places.)
2. Empty lines are dropped.
    If the command returns no non-empty output, the variable has no values and any target that references it produces no paths.
3. Integer-looking lines are zero-padded to four digits.
    So `jq -r 'range(0; 7)'` yields `0000`, `0001`, ..., `0006`, which sorts naturally when viewed with `ls`.

Multiple variables can be defined for a single target;
`fac` will order their evaluation automatically based on which variables appear in which definitions.
Circular variable definitions are detected and reported as errors.

Because variables are shell commands, the multi-line YAML block scalar `|` is the usual way to write longer definitions:

```yaml
variables:
  TOPIC: |
    jq -r 'keys[]' outline.json
```

#### Dependencies

Every path listed in a target's `dependencies` field is built before the target itself.
`fac` handles dependencies recursively, so arbitrarily complex dependency graphs work without further configuration.

A dependency does not have to be a declared target.
If the path already exists in the git repo, `fac` will use it directly.
But if the path does not exist and is not declared in `fac.yaml`, `fac` reports an error,
because it has no way to construct the file.
(Later tutorials show how to declare and build such files explicitly.)

Dependencies serve two purposes in `fac`:

1. **Build ordering.** A dependency is always built before any target that relies on it, even when that dependency is itself a target with its own dependencies.
2. **Rebuild detection.** If the contents of a dependency change, `fac` re-runs the `cmd` of every target that depends on it, recursively.
    Crucially, `fac` hashes the dependency's *contents*, so simply touching a file (without modifying it) will not trigger a rebuild.
    This is one of the main improvements over `make`.

#### Rebuild detection

Builds are idempotent:
re-running `fac` on a target whose dependencies have not changed is a no-op.
We can verify this by re-running the previous command and checking the `git log`:

```bash
$ fac 'page/topic1_food/about.md'
<...>
$ git log --oneline
<...> (HEAD -> master) [bot] fac page/$TOPIC/about.md
<...> create fac.yaml
<...> add gitignore
```

The `git log` is unchanged, so `fac` did not create any new commits.

Now let's modify the content of a dependency.
We overwrite `outline.json` by hand and commit the change:

```bash
$ echo '{"topic1": "cooking", "topic2": "culture"}' > outline.json
$ git add outline.json
$ git commit -m 'update outline'
<...>
```

This is analogous to a developer hand-editing a source file in a more traditional build system.
If we now ask `fac` to build `page/topic1/about.md`:

```bash
$ fac 'page/topic1/about.md'
<...>
$ git log --oneline
<...> (HEAD -> master) [bot] fac page/topic1/about.md
<...> update outline
<...> [bot] fac page/$TOPIC/about.md
<...> create fac.yaml
<...> add gitignore
```

`fac` has detected that the contents of the dependency `outline.json` have changed,
and has re-run the build command for `page/topic1/about.md`,
creating a new commit.

Notice that `outline.json` itself was not rebuilt,
because none of *its* dependencies have changed.
`fac` only rebuilds the part of the dependency graph that is actually affected.

`fac` decides whether to rebuild using **both** timestamps and content hashes.
The timestamp of each dependency is compared against the timestamp of the target
(like `make` does);
if the dependency is newer, the dependency's content hash is then compared
against the hash recorded in the target's `.facjson` file.
A rebuild only happens if both checks indicate a real change.
This means that operations like `touch`, which update timestamps but do not change contents,
will not spuriously trigger rebuilds.

This behavior extends to LLM-based targets.
If `page/$TOPIC/about.md` were generated by an LLM
(using the `description:` field instead of the `cmd:` field, as we will see in the next tutorial),
`fac` would detect the changed dependency the same way and call the LLM again,
guaranteeing that downstream outputs always reflect the current state of their inputs.

#### Merging outputs with `final.txt`

The `final.txt` target depends on `page/$TOPIC/about.md`
and merges all of the individual page files into a single document:

```bash
$ fac final.txt
<...>
$ cat final.txt
College Thesis
<...>
## page/topic1/about.md
<...>
cooking
<...>
## page/topic1_food/about.md
<...>
This section will describe the traditional foods and cooking techniques of the region.
<...>
## page/topic2/about.md
<...>
culture
<...>
## page/topic2_culture/about.md
<...>
This section will describe the social customs and cultural rituals preserved across generations.
```

Because `final.txt` depends on `page/$TOPIC/about.md`,
building it caused `fac` to rebuild `page/topic2_culture/about.md` as well
(its dependency `outline.json` had been modified but not yet propagated),
and then to run the merge command.
All of this happened as part of the single `fac final.txt` invocation, and was committed together.

Note that the glob `page/*/about.md` inside the `cmd` field
simply picks up whatever files `fac` has built under `page/` so far.
Because the `dependencies` list expands to the same set of files,
`fac` guarantees that this glob never sees a stale file.

#### Git branches

Because every file that `fac` produces is committed to git,
we can use ordinary git branching to keep multiple independent versions of the thesis around at once.

Let's create a new branch and reset it to the state right after `create fac.yaml`,
before any output had been built:

```bash
$ git checkout -b from_scratch
<...>
$ git reset --hard HEAD~4
HEAD is now at <...> create fac.yaml
```

The tip of this new branch is now at `create fac.yaml`.
None of the build outputs exist.
We rebuild everything from scratch:

```bash
$ fac final.txt
<...>
$ cat final.txt
College Thesis
<...>
## page/topic1_food/about.md
<...>
This section will describe the traditional foods and cooking techniques of the region.
<...>
## page/topic2_culture/about.md
<...>
This section will describe the social customs and cultural rituals preserved across generations.
```

The output contains the *original* values from the first version of `outline.json`.
Now switch back to `master` and observe that the on-disk contents change:

```bash
$ git checkout master
<...>
$ cat final.txt
College Thesis
<...>
## page/topic1/about.md
<...>
cooking
<...>
## page/topic1_food/about.md
<...>
This section will describe the traditional foods and cooking techniques of the region.
<...>
## page/topic2/about.md
<...>
culture
<...>
## page/topic2_culture/about.md
<...>
This section will describe the social customs and cultural rituals preserved across generations.
```

Each branch keeps its own version of the output file.
`fac` needs to know nothing about branches:
it just sees the state of the working tree,
rebuilds what needs rebuilding,
and records the result in git.
