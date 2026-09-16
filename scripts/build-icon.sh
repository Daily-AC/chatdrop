#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
source_image="$project_dir/Resources/Brand/chatdrop-logo.png"
iconset="$project_dir/build/AppIcon.iconset"
mkdir -p "$iconset"
for points in 16 32 128 256 512; do
  /usr/bin/sips -z "$points" "$points" "$source_image" --out "$iconset/icon_${points}x${points}.png" >/dev/null
  pixels=$((points * 2))
  /usr/bin/sips -z "$pixels" "$pixels" "$source_image" --out "$iconset/icon_${points}x${points}@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$iconset" -o "$project_dir/Resources/AppIcon.icns"
