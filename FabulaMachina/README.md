# FabulaMachina Project Overview

FabulaMachina is a Flask application for visualizing fac projects.

## About fac

fac is a build system for LLM based projects.

The config file `fac.yaml` defines "targets" at the top-level,
and the properties of these targets define how to build them.
Targets often have variable names inside of them which get substituted by the build system to generate paths in the filesystem.
For example, the target `characters/$CHARACTER/about.json` defines how to build the paths `characters/Didaskalos/about.json` and `characters/Dinosaur/about.json`.

A "collection" is a set of targets that exist in a common folder.
For example, the targets `characters/$CHARACTER/about.json` and `characters/$CHARACTER/character_sheet.png` would both be in the collection `characters/$CHARACTER/`.

## About FabulaMachina

The FabulaMachina system contains generic code for displaying any collection in a fac.yaml file and the "book" page that is specific to the file `../fac.yaml` which is a fac project for generating books/movies.

## Conventions

### Coding

When creating new files:
- Always create a comment at the top that explains the purpose of a file in a way that will be useful for *expert* maintainers
    - There is no need to discuss basic topics like how to use a library.
    - The discussion should focus on *why* the file exists and how it relates to the other files.
    - Use FIXME annotations to mention any future work that needs to be done.
- Functions should have appropriate documentation.
- Whenever possible, functions should be factored out into non-IO based functions that have extensive doctests and small IO-based functions that call the non-IO functions. This practice ensures that functions can be easily tested.

Code that can be generic to any fac-based system should go in the standard flask-project file locations (e.g. `routes`, `templates`, and `static`). Code that is specific to the `../fac.yaml` project should go in a `pages` subfolder (like `pages/book`).

### User Interface

Always display exact filenames to users.
