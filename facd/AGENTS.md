# About

This project is a build system for llm based projects.  Targets are defined in a 'fac.yaml' file (which acts like the Makefile). Unlike make, this system has a daemon facd that runs continuously and exposes a web interface.

## Coding Style

1. The web frontend is divided into "components". Each component has a file static/$COMPONENT.css and static/$COMPONENT.script.

1. Every javascript file should start with a comment that describes what that component does.

1. The style of a tag should never be set directly in HTML/javascript. Instead, you should et the id/class of the tag in HTML/javascript and have a separate CSS file that defines the style for that class.

## API endpoints
