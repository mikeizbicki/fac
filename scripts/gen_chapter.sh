#!/bin/bash

set -e

########################################
# process command line arguments
########################################

chapter_dir=$1
mkdir -p "$chapter_dir"
if [ -e "$chapter_dir"/text ]; then
    mv "$chapter_dir"/text "$chapter_dir"/text.old.$(date +"%Y%m%d_%H%M%S")
fi

story_dir=$(dirname "$chapter_dir")
text_file="$chapter_dir"/text

########################################
# generate output
########################################

files_for_prompt="
    $(ls $story_dir/../characters/*/about.json)
    $(dirname $story_dir)/about
    $story_dir/outline
"
for chapter in $(ls "$story_dir" | grep '^chapter' | sort -n); do
    text="$story_dir/$chapter/text"
    if [ -e "$text" ]; then
        text_simplified="$text.simplified"
        ./scripts/internal/simplify_text.sh "$text" "$text_simplified"
        files_for_prompt="$files_for_prompt
        $text_simplified"
    fi
done
echo "files_for_prompt=$files_for_prompt"

prompt="
Write the text of $(basename "$chapter_dir") following the instructions below.

$(cat prompts/chapter)

---

You should reference the files below to determine what to write in the chapter,
and ensure that the chapter fits into the overall structure of the story.
$(files-to-prompt -c $files_for_prompt)
"
#echo "$prompt"

scripts/internal/llm.sh "$chapter_dir/text" "$prompt"
