#!/bin/sh

set -e

########################################
# process command line arguments
########################################

story_dir=$1
chapter_num=$(printf "%02d\n" "$2")
chapter_dir="$story_dir/chapter$chapter_num"

########################################
# generate output
########################################

#sections=$(ls "$chapter_dir"/section* | sed 's/section//')
for path in $chapter_dir/section*; do
    section=$(echo "$path" | sed 's/^.*section//')
    ./scripts/section_sprites.sh "$story_dir" "$chapter_num" "$section"
done
