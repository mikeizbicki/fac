#!/bin/sh

set -ex

story_dir="$1"

#./scripts/gen_outline.sh "$story_dir"

mkdir -p "$story_dir/subscene"
outline_file=$story_dir/outline
num_chapters=$(cat "$outline_file" | jq '.chapters | length')

for i in $(seq -f "%02g" 1 $num_chapters); do
    chapter_dir="$story_dir/chapter$i"
    echo "$chapter_dir"
    ./scripts/gen_chapter.sh "$chapter_dir"
    ./scripts/gen_scene2.py --input_file="$chapter_dir"/text
done

./scripts/gen_markdown.py "$story_dir"
./scripts/gen_html.sh "$story_dir/text.markdown"
