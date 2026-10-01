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
>     echo '{topic1: food, topic2: culture}' > outline.json
>
> page/$TOPIC/about.md:
>   cmd: |
>     echo "$TOPIC" > page/$TOPIC/about.md
>   dependencies:
>   - outline.json
>   variables:
>     TOPIC: |
>       jq -r 'keys.[]' outline.json
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
    "topic1": "food",
    "topic2": "culture"
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

The `page/$TOPIC/about.md` is much more interesting for two reasons.

1. There is a variable `TOPIC` inside the target that allows the target to build multiple files.

    This variable will be expanded by first running the command shown in the `variables['TOPIC']` dictionary entry.
    The results will then be broken on whitespace and each entry in the resulting list will create a new "expanded target"

1. The target contains a `dependencies` list inside of it,
    and all of these dependencies will be built for us automatically when we build `page/$TOPIC/about.md`.

<!--
bash
fac 'page/$TOPIC/about.md'


Dependencies are automatically built before the target is built,
and variables are automatically evaluated and substituted into the target.

bash
git ls-files | grep -v '/\.\|^\.' # the grep removes hidden files
fac.yaml
outline.json
page/topic1/about.md
page/topic2/about.md

-->
