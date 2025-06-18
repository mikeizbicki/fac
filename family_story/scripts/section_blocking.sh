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

section_num_prev=$(printf "%02d\n" $(($section_num - 1)))
section_dir_prev="$chapter_dir/section$section_num_prev"
section_blocking_file_prev="$section_dir_prev/blocking.json"
[ -e "$section_blocking_file_prev" ] || [ "$section_num" = 00 ] || (echo "$section_blocking_file_prev" does not exist; exit 1)

########################################
# generate output
########################################

files_for_prompt="
    $(ls $story_dir/../characters/*/about.json)
"
echo "files_for_prompt=$files_for_prompt"

prompt=$(cat <<EOF
Generate the blocking for the current beat described below.
The movement and positioning should smoothly transition between the previous and next beats.
The output should be a JSON dictionary (without markdown codeblocks) with the following keys:
$(cat prompts/blocking-schema)

---
current beat
---

$(jq ".sections[$section_num]" "$chapter_text")

---
previous beat
---

$(
if [ $section_num = 00 ]; then
  echo "none"
else
  jq ".sections[$section_num-1]" "$chapter_text"
  echo "
---
previous blocking
---
$(cat "$section_blocking_file_prev")
"
fi
)

---
next beat
---

$(
if [ $section_num -eq $(jq '.sections | length - 1' "$chapter_text") ]; then
  echo "none"
else
  jq ".sections[$section_num+1]" "$chapter_text"
fi
)

---
additional files
---
$(files-to-prompt -c $files_for_prompt)
EOF
)
#echo "$prompt"

scripts/internal/llm.sh "$section_blocking_file" "$prompt"
