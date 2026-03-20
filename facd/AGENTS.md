# About

This project is a build system for llm based projects.  Targets are defined in a 'fac.yaml' file (which acts like the Makefile). Unlike make, this system has a daemon facd that runs continuously and exposes a web interface.

## Backend structure

The fac folder contains the python library for the build system.

The facd contains a FastAPI webapp that exposes the web interface to fac.

## Frontend structure

All HTML/CSS/Javascript is included in the facd/static folder.
Within this folder are the following subfolders:
- external:
    - contains standard files for external libs
    - the contents of this folder should never be modified by AI agents
- core:
    - tabs.js:
        - defines the main UI interface (2 pane layout, where info is displayed in tabs that can be moved between the panes)
        - does not interact with the backend
    - nodes.js and monitor_files.js:
        - contains code that interacts with the FastAPI backend
        - all of the ui_common files depend on this code
- ui_tabs:
    - contains the main interfaces that the user interacts with
    - each file is in charge of exactly one tab
    - these tabs always use the interface in nodes.js to display files/targets to the user
- ui_common:
    - each of these files modifies some aspect of how a node gets displayed
    - these files only depend on the core/nodes.js interface

## Coding Style

1. Every javascript file must start with a comment that describes what that file does.

1. The style of a tag should never be set directly in HTML/javascript.
    - Instead, you should et the id/class of the tag in HTML/javascript and have a separate CSS file that defines the style for that class.
    - Every file XXX.js should have a corresponding XXX.css that contains these styles.
    - 
