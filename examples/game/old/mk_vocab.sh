#!/bin/sh

MODEL=anthropic/claude-sonnet-4-0
SYSTEM=''

llm -s $SYSTEM -m $MODEL > vocab.md <<EOF
Create a list of key greek/english terms for the following board game description.
The list should be markdown formatted and divided into 2 main sections:
- Vocabulary
    - markdown table that provides the greek and an english gloss
    - separate tables for nouns/verbs/adjectives
    - separate tables for different sections of the game
- Key phrases
    - a list of key phrases that should be used at different parts of the game
    - the phrases should provide both an English and Greek translation
    - the phrases should illustrate the difference between the nominative and accusative

$(files-to-prompt -c game_description)
EOF
