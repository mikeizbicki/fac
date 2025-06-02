#!/bin/bash

set -e
export $(cat .env | xargs)

instructions="$2"
if [ -z "$instructions" ]; then
    echo "Error: no instructions specified"
    exit 1
fi

chapter_dir=$1
if [ -z "$chapter_dir" ]; then
    echo "Error: no chapter dir specified"
    exit 1
fi
if [ ! -d "$chapter_dir" ]; then
    echo "$chapter_dir does not exist or is not a directory"
    exit 1
fi

base_dir=$(dirname "$chapter_dir")
chapter_prompt_file="$base_dir"/chapter-prompt
system_prompt_file="$base_dir"/system-prompt

text_file="$chapter_dir"/text
if [ ! -e "$text_file" ]; then
    echo "$text_file does not exist"
    exit 1
fi

prompt_file="$chapter_dir"/prompt
if [ ! -e "$prompt_file" ]; then
    echo "$prompt_file does not exist"
    exit 1
fi

#files_for_prompt=''
files_for_prompt="characters
$prompt_file
$chapter_prompt_file
"
for file in $(ls "$base_dir" | sort); do
    if [ "$file" == "$(basename "$chapter_dir")" ]; then
        break
    fi
    files_for_prompt="$files_for_prompt
$base_dir/$file/text.simplified"
done
echo "files_for_prompt=$files_for_prompt"

prompt="
Perform the following task on the input file:

$(echo "$instructions")

The input file is:

$(cat "$text_file")

The files below are related to how the input file was generated.
You may reference these files for consistency purposes,
but do not make any major structural changes based on these files.
$(files-to-prompt $files_for_prompt)
"

echo "prompt token count=$(ttok "$prompt" 2> /dev/null)"
time llm --no-log -m anthropic/claude-sonnet-4-0 -s "$(ls "$system_prompt_file")" "$prompt" > "$text_file.mod"
echo "output token count=$(ttok "$(cat "$text_file.mod")" 2> /dev/null)"
