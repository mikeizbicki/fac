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

########################################
# generate output
########################################

files_for_prompt="
$story_dir/outline
"
echo "files_for_prompt=$files_for_prompt"

prompt=$(cat <<EOF
Output in JSON with no markdown formatting.
Based on the outline below, create a list of 2-4 locations where the story will take place.
Each entry in the list will be a JSON dictionary with the following keys:
- "name"
- "description": a detailed description 5-10 sentences long describing the location; the description should relate to what is happening in the plot
- "sublocations": a JSON list of 2-5 sublocations inside the location; every scene in the story will happen at one of these sublocations; every list should contain both an indoor sublocation and an outdoor sublocation (e.g. if the location is a house, then one sublocation could be "front yard" and the other could be "kitchen"); each entry of the list should be a JSON dict with the following keys:
  - "name"
  - "type": either "indoor" or "outdoor"
  - "description": a 2-4 sentence description of the sublocation; the description should be suitable for drawing an animation picture with the sublocation as the background of the image; the description should mention any features that will be relevant to the plot

You should plan for the locations and sublocations to be reused in many different chapters throughout the story.
It is especially good if the characters later in the story will be able to visit or refer back to (sub)locations that were used earlier in the story.

---

$(files-to-prompt -c $files_for_prompt)
EOF
)
#echo "$prompt"

scripts/internal/llm.sh "$story_dir/locations.json" "$prompt"

