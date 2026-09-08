# Basic fac Tutorial

`fac` is a build system designed for automating AI workflows.
It works with all AI providers (e.g. GPT, Claude, Gemeni, Deepseek, Qwen) and all modalities (e.g. text, image, video, audio).

In this tutorial, we will create a pipeline for generating a college senior thesis using AI.

**What is a build system?**

A *build system* is a tool that converts a project's source code into something we can actually run.
For most programming languages, a *compiler* processes a single file;
then the build system calls the compiler on files in the many project files in the right order.
For example in the python world, `python` is the "compiler" and `pip` is the "build system".
In fac, the I is the "compiler" and `fac` is the "build system".
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
$ git init >/dev/null
```

> **NOTE:**
> This tutorial is fully reproducible and tested using [byexample](https://byexamples.github.io/byexample/).
> `byexample` tests markdown code by running the code in the code blocks and verifying that the output exactly matches output provided.
> The `>/dev/null` in the `git init` command above just hides the output of the command,
> which is necessary for the test cases.
> This tutorial assumes this type of basic knowledge of the shell and git.

Now we create a simple `fac.yaml` file.
This file defines all of the targets that fac can build.

```bash
$ cat > fac.yaml <<'EOF'
> "outline.json":
>   cmd: |
>     echo '{"topic1": "food", "topic2": "culture"}' > outline.json
>
> "page/$TOPIC/about.md":
>   cmd: |
>     echo "$TOPIC" > page/$TOPIC/about.md
>   dependencies:
>   - outline.json
>   variables:
>     TOPIC: |
>       jq -r 'keys.[]' outline.json
> EOF
```

The top level entries in `fac.yaml` define the *targets*
(build system jargon for files that `fac` can build).
The `fac.yaml` above defines two targets:
- `outline.json`
- `page/$TOPIC/about.md`

To build targets, we must have a clean repo.
So every time we modify the `fac.yaml` (or any other file), we must commit it.

```bash
$ git add fac.yaml
$ git commit -m 'creat fac.yaml' >/dev/null
```

## Building

To build a target, we pass it to the `fac` command.

```bash
$ fac 'page/$TOPIC/about.md'
```

Dependencies are automatically built before the target is built,
and variables are automatically evaluated and substituted into the target.

```bash
$ git ls-files | grep -v '/\.\|^\.' # the grep removes hidden files
fac.yaml
outline.json
page/topic1/about.md
page/topic2/about.md
```
