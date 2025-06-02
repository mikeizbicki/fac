#!/bin/bash

set -e
export $(cat .env | xargs)

outfile="$1"
prompt="$2"

echo "prompt token count=$(ttok "$prompt" 2> /dev/null)"
time llm --no-log -m anthropic/claude-sonnet-4-0 -s "$(cat prompts/system)" "$prompt" > "$outfile"
echo "output token count=$(ttok "$(cat "$outfile")" 2> /dev/null)"

