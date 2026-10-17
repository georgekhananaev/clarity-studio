#!/bin/zsh
set -eu
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
  print -u2 'Install uv with: brew install --force-bottle uv'
  exit 1
fi
if [[ ! -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg && ! -x /usr/local/opt/ffmpeg-full/bin/ffmpeg ]]; then
  HOMEBREW_NO_AUTO_UPDATE=1 brew install --force-bottle ffmpeg-full
fi
uv sync --python "$(command -v python3)" --no-install-project --no-build
./clarity-cli doctor
print 'Ready. Double-click Launch Clarity.command to open the editor.'
