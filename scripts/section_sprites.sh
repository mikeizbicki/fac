#!/bin/sh

set -e

########################################
# process command line arguments
########################################

story_dir=$1
chapter_num=$(printf "%02d\n" "$2")
chapter_dir="$story_dir/chapter$chapter_num"
chapter_text="$chapter_dir"/text 
[ -e "$chapter_text" ] || (echo "$chapter_text" does not exist; exit 1)

section_num=$(printf "%02d\n" "$3")
section_dir="$chapter_dir/section$section_num"
mkdir -p "$section_dir"
section_blocking_file="$section_dir/blocking.json"

########################################
# generate output
########################################

num_characters=$(jq '.characters | length' "$section_blocking_file")

for i in $(seq 0 $((num_characters - 1))); do 
    character_name=$(jq ".characters[$i].name" "$section_blocking_file" | tr -d '"' | tr '[:upper:]' '[:lower:]')
    echo generating sprite $i for character $character_name
    character_dir="$story_dir/../characters/$character_name"
    prompt="
The entire character should fit in the picture with nothing cut off.
The background should be transparent.

---
character pose information
---
$(jq ".characters[$i].description" "$section_blocking_file")

---
character about
---
$(jq ".Appearance" "$character_dir/about.json")
"
    #echo "$prompt"

    modelsheet="$character_dir/modelsheet.png"
    #echo $modelsheet

    output_file="$section_dir/$character_name.png"

    if ! [ -f $output_file ]; then
        ./scripts/internal/gen_image.py "$output_file" "$prompt" "$modelsheet" --size=1024x1536 &
    fi

done
wait
