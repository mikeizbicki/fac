#!/bin/bash

set -e

book_dir="$1"
outline_file=$1/outline
num_chapters=$(grep -i '^#.*Chapter' "$outline_file" | wc -l)

for i in $(seq 1 $num_chapters); do
    chapter_dir="$book_dir/chapter$i"
    echo "$chapter_dir"
    ./scripts/gen_chapter.sh "$chapter_dir"
done
