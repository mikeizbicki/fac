#!/bin/bash

set -e
export $(cat .env | xargs)

outfile="$1"
prompt="$2"

#MODEL=gpt-4.1
MODEL=anthropic/claude-sonnet-4-0
price_input=3
price_output=15

input_tokens=$(ttok "$(cat prompts/system) $prompt" 2> /dev/null)
input_price=$(bc -l <<< "scale=3; $input_tokens * $price_input / 1000000")
echo "input_tokens=$input_tokens; input_price=$input_price"
time llm --no-log -m $MODEL -s "$(cat prompts/system)" "$prompt" > "$outfile"

output_tokens=$(ttok "$(cat "$outfile")" 2> /dev/null)
output_price=$(bc -l <<< "scale=3; $output_tokens * $price_output / 1000000")
echo "output_tokens=$output_tokens; output_price=$output_price"

all_price=$(bc -l <<< "$input_price + $output_price")
echo "all_price=$all_price"
