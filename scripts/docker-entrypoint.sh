#!/bin/sh
set -e

PROTOCOL_STORAGE="${PROTOCOL_DIR:-/app/storage/protocols}"
mkdir -p "$PROTOCOL_STORAGE"

exec "$@"
