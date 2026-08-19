#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  python3 -m venv .venv || { echo "need python3-venv"; exit 1; }
  ./.venv/bin/pip install -r requirements.txt
fi
exec ./.venv/bin/python -m permify "$@"
