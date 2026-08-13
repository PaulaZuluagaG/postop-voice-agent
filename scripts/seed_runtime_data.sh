#!/bin/sh
# Seed bind-mounted runtime dirs from image bootstrap when empty (first docker up).
set -e

PROTOCOL_STORAGE="${PROTOCOL_DIR:-/app/storage/protocols}"
BOOTSTRAP_PROTOCOLS="${BOOTSTRAP_PROTOCOL_DIR:-/app/bootstrap/protocols}"
HF_RUNTIME="${HF_HOME:-/app/.cache/huggingface}"
HF_BOOTSTRAP="${HF_BOOTSTRAP_DIR:-/app/bootstrap/huggingface}"

mkdir -p "$PROTOCOL_STORAGE"

_protocols_empty() {
  [ -z "$(find "$PROTOCOL_STORAGE" -mindepth 1 -name 'protocol.json' -print -quit 2>/dev/null)" ]
}

if [ -d "$BOOTSTRAP_PROTOCOLS" ] && _protocols_empty; then
  echo "==> Seeding protocols from bootstrap -> $PROTOCOL_STORAGE"
  cp -a "$BOOTSTRAP_PROTOCOLS/." "$PROTOCOL_STORAGE/"
fi

_hf_empty() {
  [ -z "$(find "$HF_RUNTIME" -mindepth 1 -print -quit 2>/dev/null)" ]
}

if [ -d "$HF_BOOTSTRAP" ] && _hf_empty; then
  echo "==> Seeding Hugging Face cache from bootstrap -> $HF_RUNTIME"
  mkdir -p "$HF_RUNTIME"
  cp -a "$HF_BOOTSTRAP/." "$HF_RUNTIME/"
fi
