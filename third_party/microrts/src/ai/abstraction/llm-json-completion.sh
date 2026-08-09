#!/bin/sh
#SBATCH --gpus-per-node=1
#SBATCH -e ./output.err
#SBATCH -o ./output.out
#SBATCH --nodelist=node008

# --- Function to safely escape prompt for JSON ---
json_escape() {
  local input="$1"
  printf '%s' "$input" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

# --- Inputs ---
MODEL=$1
PROMPT_FILE=$2
FORMAT_FILE=$3

# --- Read file contents ---
PROMPT=$(cat "$PROMPT_FILE")
FORMAT=$(cat "$FORMAT_FILE")

# --- Escape prompt string ---
ESCAPED_PROMPT=$(json_escape "$PROMPT")

# --- Build JSON payload ---
JSON_PAYLOAD=$(cat <<EOF
{
  "model": "$MODEL",
  "prompt": $ESCAPED_PROMPT,
  "stream": false,
  "format": $FORMAT
}
EOF
)

# --- Send request ---
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d "$JSON_PAYLOAD"
