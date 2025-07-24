#!/bin/sh

set -e

path=$1
if [ -z "$1" ]; then
  echo "Please provide a path as an argument."
  exit 1
fi

filename=$(basename "$path")
timestamp=$(date +"%Y-%m-%dT%H:%M:%S.%N")
filename1=".${filename}.fac.${timestamp}"
path1="$(dirname "$path")/${filename1}"

cp "$path" "$path1"

SYSTEM="The output should be a patch file that modifies the document below as directed by the prompt. (Do not output a modified file directly, output a patch that can be applied to modify the file.) There should be no other output, including no markdown code blocks and no explanation. Do not make any changes unless you are specifically asked (e.g. do not fix any formatting issues, typos, or bugs unless the prompt asks you to).  Ensure that the line numbers used match the line numbers provided by \`nl\`.

\`\`\`
\$ nl \"$path\"
$(nl "$path")
\`\`\`
"
MODEL=anthropic/claude-sonnet-4-0
llm -xs "$SYSTEM" > "$path1.patch"

cat "$path1.patch"
patch -l "$path" "$path1.patch"
