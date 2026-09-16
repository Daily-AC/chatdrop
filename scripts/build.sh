#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
app="$project_dir/build/ChatDrop.app"
extension="$app/Contents/PlugIns/ChatDropShare.appex"
target="$(uname -m)-apple-macos14.0"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$extension/Contents/MacOS"
bash "$project_dir/scripts/build-icon.sh"
cp "$project_dir/Resources/AppIcon.icns" "$app/Contents/Resources/AppIcon.icns"
/usr/bin/clang -target "$target" -c "$project_dir/Sources/ExtensionMain.c" -o "$project_dir/build/ExtensionMain.o"
/usr/bin/swiftc -target "$target" -swift-version 5 -O -parse-as-library -module-name ChatDropShare \
  "$project_dir/Sources/Inbox.swift" "$project_dir/Sources/Conversations.swift" \
  "$project_dir/Sources/ConversationPicker.swift" "$project_dir/Sources/ShareViewController.swift" \
  "$project_dir/build/ExtensionMain.o" -o "$extension/Contents/MacOS/ChatDropShare"
/usr/bin/swiftc -target "$target" -swift-version 5 -O -parse-as-library \
  "$project_dir/Sources/Inbox.swift" "$project_dir/Sources/Conversations.swift" \
  "$project_dir/Sources/ConversationPicker.swift" "$project_dir/Sources/App.swift" -o "$app/Contents/MacOS/ChatDrop"
/usr/bin/plutil -convert binary1 -o "$app/Contents/Info.plist" "$project_dir/Resources/App-Info.plist"
/usr/bin/plutil -convert binary1 -o "$extension/Contents/Info.plist" "$project_dir/Resources/Share-Info.plist"
/usr/bin/codesign --force --sign - --entitlements "$project_dir/Resources/Share.entitlements" "$extension"
/usr/bin/codesign --force --sign - "$app"
/usr/bin/codesign --verify --deep --strict "$app"
# Refresh bundle-level metadata for in-place upgrades (Spotlight and app icons).
touch "$extension" "$app"
echo "$app"
