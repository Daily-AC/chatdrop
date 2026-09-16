# Contributing

Small fixes and reproducible export-format reports are welcome.

Run `python3 -m unittest discover -s tests -v` before submitting CLI changes. Native
changes also need `bash scripts/build.sh` and a real system-sharing check. Report the
macOS version, architecture, and WeChat version used; a successful compile is not
runtime support for a new platform.

Use synthetic fixtures shaped like the actual export. Do not commit personal chats,
images, videos, SQLite stores, receipts, credentials, or machine-specific paths.

For parser issues, describe the format and provide a minimal redacted sample. For
missing media, distinguish a filename mentioned in TXT from a file present in ZIP.
Preserve original files and provenance when changing matching behavior. When no
stable source identity exists, document ambiguity instead of claiming exact recovery.
