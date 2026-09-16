#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
app="$project_dir/build/ChatDrop.app"
/usr/bin/codesign --verify --deep --strict "$app"
version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist")
architecture=$(/usr/bin/lipo -archs "$app/Contents/MacOS/ChatDrop")
case "$architecture" in arm64|x86_64) ;; *) echo "Unsupported package architecture: $architecture" >&2; exit 1 ;; esac
name="ChatDrop-$version-macos-$architecture"
staging=$(mktemp -d "$project_dir/build/package.XXXXXX")
trap 'rm -r "$staging"' EXIT
mkdir -p "$staging/$name/cli" "$staging/$name/scripts" "$project_dir/build/releases"
/usr/bin/ditto "$app" "$staging/$name/ChatDrop.app"
cp "$project_dir/cli/chatdrop.py" "$staging/$name/cli/chatdrop.py"
cp "$project_dir/scripts/install-cli.sh" "$staging/$name/scripts/install-cli.sh"
cp "$project_dir/LICENSE" "$staging/$name/LICENSE"
cat > "$staging/$name/README.txt" <<'EOF'
ChatDrop

1. Copy ChatDrop.app to Applications and open it once.
2. Enable its Sharing extension in System Settings if it is not listed.
3. In WeChat, select messages and use:
   转发到其他应用 > 选择电脑中的应用 > ChatDrop
4. Choose or create a conversation and save.

CLI requires Python 3.9+ on PATH. In this extracted folder, run:
  bash scripts/install-cli.sh
Add ~/.local/bin to PATH, then run:
  chatdrop conversations
  chatdrop search --conversation 'Project group' --from 2026-09-01 --to 2026-09-16 --all

This build targets macOS 14+, and was tested on Apple Silicon macOS 26.6.2.
It is ad-hoc signed, not notarized. If macOS blocks first launch, use
System Settings > Privacy & Security > Open Anyway after reviewing the source.

Records stay in ~/Downloads/ChatDrop and ~/Library/Application Support/ChatDrop.
Source archives are preserved. Export-derived matching has no native message IDs;
identical same-minute messages in separate exports can remain ambiguous.
EOF
archive="$project_dir/build/releases/$name.zip"
/usr/bin/ditto -c -k --keepParent "$staging/$name" "$archive"
(cd "$project_dir/build/releases" && /usr/bin/shasum -a 256 "$name.zip" > "$name.zip.sha256")
echo "$archive"
