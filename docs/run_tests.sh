#!/bin/sh

podman build . -t fac
podman run -it fac byexample --no-enhance-diff -l shell docs/*.md
