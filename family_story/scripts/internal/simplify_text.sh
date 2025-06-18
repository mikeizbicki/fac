#!/bin/bash

set -e

text_file="$1"
cp "$text_file" "$text_file.simplified"

# remove markdown images
sed -i '/!\[.*\](.*)/d' "$text_file.simplified"

# remove Vocab section
sed -i '/## Vocabulary/,/## Grammar/{ /## Grammar/!d }' "$text_file.simplified"

# remove niqqud / daggesh marks
sed -i 's/[ְֱֲֳִֵֶַָֹ־ּ]//g' "$text_file.simplified"

# clean json objects
jq 'walk(if type == "object" then del(.image_description, .stage_directions, .title_target, .vocabulary) else . end)' "$text_file.simplified" > "$text_file.simplified.temp"
mv "$text_file.simplified.temp" "$text_file.simplified"

echo "simplified token count=$(ttok "$(cat "$text_file.simplified")" 2> /dev/null)"
