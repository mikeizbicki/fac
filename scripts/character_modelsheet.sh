#!/bin/sh

set -e

########################################
# process command line arguments
########################################

char_dir=$1
char_about_path="$char_dir/about.json"
[ -e "$char_about_path" ] || (echo "$char_about_path" does not exist; exit 1)
modelsheet_path="$char_dir/modelsheet.png"
rawimages_path="$char_dir/raw_images"

########################################
# generate output
########################################

prompt="
Take the input images and generate a model sheet of the represented person.
The model sheet should:
1. have a transparent background
2. have the following representations of the person:
    - profile (left)
    - profile (right)
    - straight-on
    - back
3. each representation should be in its own frame
4. all frames should have consistent styling, clothing, and appearance
5. there should be no background objects, only the character
6. clothing should be solid colors and without logos

Style: cartoon, bright colors, bold outlines, fun for kids
"

./scripts/internal/gen_image.py "$modelsheet_path" "$prompt" $rawimages_path/* --quality=high
