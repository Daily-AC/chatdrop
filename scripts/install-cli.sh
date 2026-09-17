#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cli_dir="$HOME/.local/share/chatdrop"
bin_dir="$HOME/.local/bin"
skill_dir="$cli_dir/skills/chatdrop"
agent_homes=("$HOME/.claude" "$HOME/.codex")
mkdir -p "$cli_dir" "$bin_dir" "$skill_dir"
if [[ -e "$bin_dir/chatdrop" || -L "$bin_dir/chatdrop" ]]; then
  if [[ ! -L "$bin_dir/chatdrop" || "$(readlink "$bin_dir/chatdrop")" != "$cli_dir/chatdrop" ]]; then
    echo "Refusing to replace an unrelated chatdrop command." >&2
    exit 1
  fi
fi
for agent_home in "${agent_homes[@]}"; do
  link="$agent_home/skills/chatdrop"
  if [[ -e "$link" || -L "$link" ]]; then
    if [[ ! -L "$link" || "$(readlink "$link")" != "$skill_dir" ]]; then
      echo "Refusing to replace an unrelated chatdrop skill at $link." >&2
      exit 1
    fi
  fi
done
install -m 755 "$project_dir/cli/chatdrop.py" "$cli_dir/chatdrop"
ln -sfn "$cli_dir/chatdrop" "$bin_dir/chatdrop"
install -m 644 "$project_dir/skills/chatdrop/SKILL.md" "$skill_dir/SKILL.md"
echo "$bin_dir/chatdrop"
linked=""
for agent_home in "${agent_homes[@]}"; do
  [[ -d "$agent_home" ]] || continue
  mkdir -p "$agent_home/skills"
  ln -sfn "$skill_dir" "$agent_home/skills/chatdrop"
  echo "$agent_home/skills/chatdrop"
  linked="yes"
done
if [[ -z "$linked" ]]; then
  echo "No ~/.claude or ~/.codex found; skill is at $skill_dir" >&2
fi
