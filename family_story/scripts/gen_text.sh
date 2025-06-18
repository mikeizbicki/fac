#!/bin/bash

set -e
export $(cat .env | xargs)

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
#if [ -e "$text_file" ]; then
    #new_text_file=$(dirname $text_file)/.text.$(date +"%Y%m%d_%H%M%S")
    #echo "$text_file exists; moving to $new_text_file"
    #mv "$text_file" "$new_text_file"
#fi

prompt_file="$chapter_dir"/prompt
if [ ! -e "$prompt_file" ]; then
    echo "$prompt_file does not exist"
    exit 1
fi

#files_for_prompt=''
files_for_prompt='characters
'
for file in $(ls "$base_dir" | sort); do
    if [ "$file" == "$(basename "$chapter_dir")" ]; then
        break
    fi
    files_for_prompt="$files_for_prompt
$base_dir/$file/text.simplified"
done
echo "files_for_prompt=$files_for_prompt"

prompt="
$(cat "$prompt_file")

$(cat "$chapter_prompt_file")

The files below are previous chapters.
The next chapter should build off of these results.
$(files-to-prompt $files_for_prompt)
"

echo "prompt token count=$(ttok "$prompt" 2> /dev/null)"
time llm --no-log -m anthropic/claude-sonnet-4-0 -s "$(ls "$system_prompt_file")" "$prompt" > "$text_file"
echo "output token count=$(ttok "$(cat "$text_file")" 2> /dev/null)"

scripts/simplify_text.sh "$text_file"
