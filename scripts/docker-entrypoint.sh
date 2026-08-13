#!/bin/sh
set -e

/app/scripts/seed_runtime_data.sh
exec "$@"
