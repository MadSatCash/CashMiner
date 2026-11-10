#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m cashminer gui
