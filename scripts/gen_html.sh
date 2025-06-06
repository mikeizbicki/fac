#!/bin/bash

# Check if the input file exists
if [ ! -f "$1" ]; then
  echo "Error: File not found."
  exit 1
fi

# Remove the extension from the filename
filename="${1%.*}"

# Convert markdown to html using pandoc
pandoc -s -o "${filename}.html" "$1" -f markdown-implicit_figures \
    --include-in-header=<(echo "<style>$(cat common/bubble.css)</style>") \
    --include-in-header=<(echo "<script>$(cat common/bubble.js)</script>")\
    --include-in-header=<(echo "<style>$(cat common/book.css)</style>") \
    --include-in-header=<(echo "<script>$(cat common/book.js)</script>")
