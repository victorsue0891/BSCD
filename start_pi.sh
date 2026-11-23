#!/bin/sh
# Run within the Raspberry Pi graphical desktop session.
set -eu
project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$project_dir/main.py" --fullscreen "$@"
