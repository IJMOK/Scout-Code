#!/usr/bin/env bash
# Download the AI models. Run ONCE while the Pi still has internet.
#
#   ./setup/download-models.sh            # the default 3B model (recommended)
#   ./setup/download-models.sh all        # 1.5B, 3B, 4B and 7B, to compare with benchmark.py
#   ./setup/download-models.sh 1.5b 7b    # pick some
#
# Models go in /opt/scout/models (override with MODELS_DIR=...).
set -euo pipefail

MODELS_DIR="${MODELS_DIR:-/opt/scout/models}"
mkdir -p "$MODELS_DIR"

declare -A URLS=(
  # Fastest. Good for simple changes; makes more mistakes.
  [1.5b]="https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
  # Recommended balance of speed and quality on a Pi 5.
  [3b]="https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
  # Newer general model, often better at following the edit format. Slower than 3B.
  [4b]="https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
  # Best code, but roughly half the speed of 3B. Only if your scouts are patient.
  [7b]="https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
)
declare -A FILES=(
  [1.5b]="qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
  [3b]="qwen2.5-coder-3b-instruct-q4_k_m.gguf"
  [4b]="qwen3-4b-instruct-2507-q4_k_m.gguf"
  [7b]="qwen2.5-coder-7b-instruct-q4_k_m.gguf"
)

wanted=("$@")
[[ ${#wanted[@]} -eq 0 ]] && wanted=(3b)
[[ "${wanted[0]}" == "all" ]] && wanted=(1.5b 3b 4b 7b)

for key in "${wanted[@]}"; do
  url="${URLS[$key]:-}"
  if [[ -z "$url" ]]; then
    echo "Unknown model '$key'. Choose from: ${!URLS[*]}" >&2
    exit 1
  fi
  dest="$MODELS_DIR/${FILES[$key]}"
  if [[ -s "$dest" ]]; then
    echo "✓ $key already downloaded: $dest"
    continue
  fi
  echo "↓ Downloading $key model (this can take a while)…"
  curl -L --fail --retry 5 --retry-delay 5 -C - -o "$dest.part" "$url"
  # Sanity checks: real GGUF files start with "GGUF" and are hundreds of MB.
  if [[ "$(head -c 4 "$dest.part")" != "GGUF" ]] || [[ $(stat -c %s "$dest.part") -lt 100000000 ]]; then
    echo "✗ $key download doesn't look like a model file. Check the URL in this script." >&2
    rm -f "$dest.part"
    exit 1
  fi
  mv "$dest.part" "$dest"
  echo "✓ $key saved to $dest"
done

# The default model the services use.
if [[ ! -e "$MODELS_DIR/current.gguf" && -s "$MODELS_DIR/${FILES[3b]}" ]]; then
  ln -s "$MODELS_DIR/${FILES[3b]}" "$MODELS_DIR/current.gguf"
fi
echo
echo "Models in $MODELS_DIR:"
ls -lh "$MODELS_DIR"
echo
echo "To switch model:  sudo ln -sf $MODELS_DIR/<file>.gguf $MODELS_DIR/current.gguf && sudo systemctl restart scout-llm"
