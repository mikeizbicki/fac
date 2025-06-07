#!/bin/bash

set -e

########################################
# process command line arguments
########################################

story_dir=$1
if [ -z "$story_dir" ]; then
    echo "Error: no story dir specified"
    exit 1
fi
if [ ! -d "$story_dir" ]; then
    echo "$story_dir does not exist or is not a directory"
    exit 1
fi

story_about_file="$story_dir/about"
if [ ! -e "$story_about_file" ]; then
    echo "$story_about_file does not exist"
    exit 1
fi

########################################
# generate output
########################################

files_for_prompt="
    $(ls $story_dir/../characters/*/about.json)
    $story_about_file
    $(dirname $story_dir)/about
"
echo "files_for_prompt=$files_for_prompt"

prompt="
Create an outline for the story described in the file \`$story_about_file\`.
$(cat prompts/outline)

---

$(files-to-prompt -c $files_for_prompt)
"
#echo "$prompt"

scripts/internal/llm.sh "$story_dir/outline" "$prompt"
