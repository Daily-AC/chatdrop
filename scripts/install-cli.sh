#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cli_dir="$HOME/.local/share/chatdrop"
bin_dir="$HOME/.local/bin"
mkdir -p "$cli_dir" "$bin_dir"
if [[ -e "$bin_dir/chatdrop" || -L "$bin_dir/chatdrop" ]]; then
  if [[ ! -L "$bin_dir/chatdrop" || "$(readlink "$bin_dir/chatdrop")" != "$cli_dir/chatdrop" ]]; then
    echo "Refusing to replace an unrelated chatdrop command." >&2
    exit 1
  fi
fi
install -m 755 "$project_dir/cli/chatdrop.py" "$cli_dir/chatdrop"
ln -sfn "$cli_dir/chatdrop" "$bin_dir/chatdrop"
echo "$bin_dir/chatdrop"
