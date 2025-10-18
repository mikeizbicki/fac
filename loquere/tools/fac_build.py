import pathlib
import os

from loquere.utils import tool_print
from fac.__main__ import BuildSystem

def gen_tool(messages):
    def tool(target):
        tool_print(f'fac_build({target})')

        build_system = BuildSystem(
            targets=[target],
            include_chat=messages,
            overwrite=True,
            )
    return tool

data = {
    "type": "function",
    "function": {
        "name": "fac_build",
        "description": "Runs a build target specified in the `fac.yaml` file.  Any files that are managed by `fac.yaml` should be created using this command.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "A target is a top-level entry in the `fac.yaml` file.  A target can correspond to one or more files.  Recall that variables can be pattern matched, and so a path of `example/file.json` would match a target of `$VAR/file.json` but not a target of `dir/$VAR/file.json`. Also recall that the target string must exactly match a target in the `fac.yaml` file (modulo these variable substitutions); for example, `outline` does not match the target `outline.json` and will result in an error.",
                },
            },
            "required": ["path"],
        },
    },
}

