#!/bin/bash

set -e

story_dir="$1"
chapter="$2"

chapter_dir="$story_dir/chapter$chapter"
chapter_text="$chapter_dir"/text 
[ -e "$chapter_text" ] || (echo "$chapter_text" does not exist; exit 1)
num_sections=$(cat "$chapter_text" | jq '.sections | length')

for i in $(seq -f "%02g" 0 $(($num_sections - 1))); do
    ./scripts/section_blocking.sh "$story_dir" "$chapter" "$i"
done

