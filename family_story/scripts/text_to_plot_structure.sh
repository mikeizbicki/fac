#!/bin/sh

prompt=$(cat<<EOF
Convert the plot structure below into a standardized format.
The output should be JSON (with no markdown code block) with the following keys:
- "name": name of the plot structure
- "advantages": a list of 2-5 strings that describe the advantages of the plot structure; the list should focus on helping a writer determine when to use this structure as opposed to other structures
- "disadvantages": the opposite of advantages; a list of 2-5 strings that helps a writer determine when not to use the plot structure; it is okay for this list to be empty if the source does not mention disadvantages
- "elements": a list of elements that form the structure; each element in the list should be a JSON dict with the following keys
  - "name": name of the element
  - "description": a <10 sentence guide for writers to determine what to write in this portion of the plot
  - "relative_length": every element should be assigned a percent score that is the relative length that this particular plot element should occupy for the story; all "relative_length" sections should sum to 100%
  - "examples": a list of example plot descriptions using this element; these examples should be taken directly from the input file and you should not create them yourself; it is okay for the list to be empty if there are no examples; each example should be 2-5 sentences long

$(files-to-prompt -c $1)
EOF
)

./scripts/internal/llm.sh "prompts/story_structures/$(basename "$1")" "$prompt"
