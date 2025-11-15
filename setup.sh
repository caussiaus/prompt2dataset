#!/bin/bash
set -e

# Rest of setup omitted for brevity...

echo "Reading models.config..."
OLLAMA_MODELS=$(grep '^ollama:' models.config | cut -d: -f2)
HF_MODELS=$(grep '^huggingface:' models.config | cut -d: -f2)

# Download Ollama models
if command -v ollama &> /dev/null; then
  while read -r MODEL; do
    [ -n "$MODEL" ] && ollama pull $MODEL
  done < <(grep -A100 '^ollama:' models.config | tail -n +2 | sed 's/^- //g' | grep -v '^$')
else
  echo "Ollama not installed, skipping."
fi

# Download HuggingFace models (basic, for transformers)
pip install --upgrade pip
pip install transformers
while read -r MODEL; do
  [ -n "$MODEL" ] && python3 -c "from transformers import AutoModel; AutoModel.from_pretrained('$MODEL')"
done < <(grep -A100 '^huggingface:' models.config | tail -n +2 | sed 's/^- //g' | grep -v '^$')
