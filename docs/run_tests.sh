#!/bin/sh

podman build . -t fac
podman run -it -e NO_COLOR=1 -e TERM=dumb fac byexample --no-enhance-diff -l shell  --timeout=60 docs/basic_example.md
podman run -it -e NO_COLOR=1 -e TERM=dumb fac byexample --no-enhance-diff -l shell  --timeout=60 docs/error_messages.md
