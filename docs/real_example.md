# Real fac Tutorial: Generating an Essay with LLMs

`basic_example.md` introduced fac as a build system that runs shell
commands.  Real fac projects replace those shell commands with LLM
calls.  This tutorial builds an essay that way: one LLM call generates
a JSON outline, one LLM call per section drafts the body text, and a
plain shell command stitches everything into `final.md`.

Because the model outputs are not reproducible, this tutorial is
**excluded from CI** (see `docs/run_tests.sh`).  Every `fac` command
below is a real one and will call a live model; the outputs shown are
illustrative.

## API keys

fac dispatches every LLM call through the `LLM` class in `fac/LLM.py`.
That class reads the provider's API key from a standard environment
variable:

| provider   | environment variable |
| ---------- | -------------------- |
| OpenAI     | `OPENAI_API_KEY`     |
| Anthropic  | `ANTHROPIC_API_KEY`  |
| OpenRouter | `OPENROUTER_API_KEY` |
| Cerebras   | `CEREBRAS_API_KEY`   |
| Groq       | `GROQ_API_KEY`       |

The `registered_providers` dictionary at the top of `fac/LLM.py` lists
the full set of providers, their base URLs, and the name of the
environment variable each one reads.  Export the key(s) for whatever
providers you plan to use:

```bash
$ export OPENAI_API_KEY=sk-...
```

(In practice you would put this in your shell rc file or a secrets
manager rather than typing it each session.)

## Project setup

All fac projects must be in a git repo.

```bash
$ cd $(mktemp -d)
$ git init
<...>
$ echo .fac.log > .gitignore
$ git add .gitignore
$ git commit -m 'add gitignore'
<...>
```

The `.fac.log` file is where fac writes its full debug log (see
`fac/Logging.py`); it can grow large and should not be committed.

## Style guide

Rather than pin the writing style inside `fac.yaml`, we put it in a
separate hand-written file that every section can depend on:

```bash
$ cat > style_guide.md <<'EOF'
> You are drafting a history essay in the register of a Cambridge Tripos
> paper.
>
> Rules:
> - Argue directly.  Do not hedge with "arguably", "perhaps", or
>   "it could be said".
> - Prefer the past tense and concrete historical actors.
> - Cite at least one named place, person, or date per paragraph.
> - Keep sentences short and declarative.
> - Never restate the thesis verbatim; develop it.
> EOF
$ git add style_guide.md
$ git commit -m 'add style guide'
<...>
```

## The fac.yaml

```bash
$ cat > fac.yaml <<'EOF'
> outline.json:
>   description: |
>     Produce a structured outline for the essay topic given in the
>     additional user instructions.  The essay is a general-purpose
>     history essay, not tied to any particular subject.
>
>     Each supporting argument should be a single sentence that stands
>     on its own.
>   schema: |
>     {
>       "type": "object",
>       "properties": {
>         "section_title": {"type": "string", "description": "1-6 word English title"},
>         "main_thesis":   {"type": "string", "description": "1-3 sentence thesis statement"},
>         "supporting_arguments": {
>           "type": "array",
>           "items": {"type": "string"},
>           "minItems": 3,
>           "maxItems": 5
>         }
>       },
>       "required": ["section_title", "main_thesis", "supporting_arguments"]
>     }
>   options:
>     model: openai/gpt-5.5
>
> sections/$SECTION/about.md:
>   description: |
>     Write one full section (3-5 paragraphs) of the essay.
>
>     The overall thesis of the essay is:
>     $MAIN_THESIS
>
>     The specific argument that THIS section must make is:
>     $ARGUMENT
>
>     Ground the argument in concrete historical detail.
>   options:
>     model: openai/gpt-5-mini
>   dependencies:
>     - target: outline.json
>       include: false
>     - style_guide.md
>   variables:
>     SECTION: |
>       jq -r '.supporting_arguments | keys[]' outline.json
>     ARGUMENT: |
>       jq -r ".supporting_arguments[$SECTION]" outline.json
>     MAIN_THESIS: |
>       jq -r '.main_thesis' outline.json
>
> final.md:
>   cmd: |
>     {
>       jq -r '"# " + .section_title'  outline.json
>       echo
>       jq -r .main_thesis            outline.json
>       for f in sections/*/about.md; do
>         echo
>         echo "## $f"
>         echo
>         cat "$f"
>       done
>     } > final.md
>   dependencies:
>     - sections/$SECTION/about.md
> EOF
$ git add fac.yaml
$ git commit -m 'create fac.yaml'
<...>
```

Three features are exercised here beyond what `basic_example.md` shows:

- **A target without `cmd:` calls an LLM.**  fac dispatches on the
  `mime-type` derived from the file extension (see
  `_configdict_to_targets` in `fac/Config.py`).  `outline.json` gets
  `text/json`, so fac calls the model and expects JSON back;
  `sections/.../about.md` gets `text/markdown`.
- **`schema:`** (an inline JSON schema) is spliced into the prompt as a
  `<formatting>` block, instructing the model to produce output that
  conforms to it.  The same field also accepts a `schema_file:` path
  (a path relative to the repo), in which case fac additionally
  validates the on-disk file after the build and repairs some common
  JSON errors.
- **`options: model:`** pins a specific model per target.  We use a
  strong model for the outline and a cheaper one for the section
  drafts.

## Bootstrapping `outline.json`

The outline's description refers to "the essay topic given in the
additional user instructions" without saying what the topic is.  We
supply it with `--include_prompt`:

```bash
$ fac outline.json --include_prompt="The essay is about how Prussia unified into Germany, compared to how the Italian states unified."
<...>
```

fac builds `outline.json`, runs `validate_file` on it (JSON
repaired/reformatted if necessary), and commits the result:

```bash
$ cat outline.json
{
    "section_title": "<...>",
    "main_thesis": "<...>",
    "supporting_arguments": [
        "<...>",
        "<...>",
        "<...>"
    ]
}
```

The schema constrains the *shape* of the output even though the wording
varies:

```bash
$ jq 'keys' outline.json
[
  "main_thesis",
  "section_title",
  "supporting_arguments"
]
$ jq '.supporting_arguments | length >= 3 and length <= 5' outline.json
true
```

> **A caveat about `--include_prompt` and rebuilds.**
> The additional user instructions are part of the prompt hash that
> fac records in `.outline.json.facjson`.  As a result, running a later
> `fac` command that touches `outline.json` *without* the same
> `--include_prompt` will look like a prompt change and cause a
> rebuild.  If you want to freeze an outline once you are happy with
> it, remove the `outline.json` target from `fac.yaml` (and commit);
> fac then treats the existing file as a plain source input.

## Building the sections and `final.md`

```bash
$ fac final.md
<...>
```

The `$SECTION` variable resolves against the outline's supporting
arguments, so fac creates one target per argument:

```bash
$ ls sections/
<...>
```

Each section is a separate LLM call.  They share the same
`style_guide.md` (attached via the `dependencies` list, which by
default puts the file's contents into the `<reference_documents>`
block of each prompt) and the same `$MAIN_THESIS`, but each one gets a
different `$ARGUMENT`.  fac runs them in parallel; the concurrency
limit is `max_workers` in `FacSettings` (`fac/Fac.py`).

The final `cmd:` just concatenates the sections under the thesis:

```bash
$ head -1 final.md
# <...>
$ grep -c '^## sections/' final.md
3
```

## Rebuilds are still idempotent

Because fac hashes both the contents of the dependencies and the
generated prompt, re-running the same command is a no-op:

```bash
$ git log --oneline
<...> (HEAD -> master) [bot] fac final.md
<...> [bot] fac outline.json --include_prompt=...
<...> create fac.yaml
<...> add style guide
<...> add gitignore
$ fac final.md
<...>
$ git log --oneline | head -1
<...> (HEAD -> master) [bot] fac final.md
```

Now edit the style guide.  Since `style_guide.md` is a dependency of
every section, every section's prompt changes and fac regenerates all
of them:

```bash
$ echo "Open with a named historical figure." >> style_guide.md
$ git add style_guide.md
$ git commit -m 'tweak style guide'
<...>
$ fac final.md
<...>
$ git log --oneline | head -3
<...> (HEAD -> master) [bot] fac final.md
<...> tweak style guide
<...> [bot] fac final.md
```

This behaviour is what makes fac useful for LLM workflows: the same
dependency-tree machinery that decides when to recompile a `.o` file
decides when to re-prompt a model.

## Other CLI flags worth knowing

- `fac --dryrun <target>` prints the prompt and the plan without
  calling any model.  Essential for debugging templates before
  spending tokens.
- `fac --overwrite <target>` forces a rebuild regardless of hashes.
- `fac --lock <target>` and `fac --unlock <target>` toggle the
  `locked` flag in the target's `.facjson` file, preventing accidental
  rebuilds of an output you are happy with.

## Where to go next

- `tests/old/greek` is a much larger working example that also uses
  the image, video, and audio modalities; see `fac/LLM.py` for the
  supported models.
- The `tests/fac_test*` scripts exercise the deterministic parts of
  fac as plain shell scripts rather than markdown tutorials.
