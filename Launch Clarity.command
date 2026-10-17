#!/bin/zsh
set -eu
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
if [[ ! -x .venv/bin/python ]]; then
  ./setup.command
fi
exec ./clarity-cli serve --open
