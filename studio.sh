#!/bin/sh
# Launcher for macOS and Linux: installs `uv` if needed, then runs studio.py with Python 3.11.
#   ./studio.sh setup | run | doctor | generate ... | benchmark | eval | vendor | test
set -e
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (Python package manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
exec uv run --python 3.11 studio.py "$@"
