<p align="center">
  <img src="Resources/Brand/chatdrop-logo.png" width="144" alt="ChatDrop logo" />
</p>

# ChatDrop

**Turn the WeChat conversations you choose to share into a local archive your AI tools can query.**

[Download for Mac](https://github.com/Daily-AC/chatdrop/releases/latest) · [简体中文](README.zh-CN.md) · [CLI reference](docs/cli.md) · [How data is stored](docs/architecture.md)

Share a chat export, choose its conversation, and query it from your terminal. Later
exports add new messages and can fill missing attachments without duplicating the
same conversation history.

ChatDrop reads the ZIPs you explicitly share or import. It uses no WeChat database
keys, message monitoring, cloud account, or built-in AI subscription.

## What works

- **A native Mac share target.** Choose ChatDrop in WeChat's “Forward to other apps” menu.
- **Named conversations.** Create a conversation once and select it on later shares.
- **Incremental imports.** Reuse matching messages and fill previously missing media.
- **An agent-friendly CLI.** Get JSON results filtered by conversation, sender, keyword,
  and date range. Fetch context and local attachment paths.
- **Local, traceable storage.** Keep original ZIPs, transcripts, and source-batch links.

## Platform status

The native receiver is currently **macOS only**. The initial package is **Apple Silicon
(arm64)**, targets macOS 14 or later, and has been tested on macOS 26.6.2. Earlier macOS
versions and Intel Macs have not yet been runtime-tested. There are no Windows,
Linux, iOS, or Android builds.

The CLI requires Python 3.9 or later and uses only the standard library. Its current
file locking and default paths are Unix/macOS-specific; cross-platform CLI support
is planned, not an existing feature.

## Get started

1. Download the [Apple Silicon release](https://github.com/Daily-AC/chatdrop/releases/latest), unzip it, copy `ChatDrop.app` into Applications, and launch it once.
2. If necessary, enable ChatDrop in **System Settings → General → Login Items &
   Extensions → Sharing** (the location varies by macOS version).
3. In WeChat, select messages and choose **转发到其他应用 → 选择电脑中的应用 → ChatDrop**.
4. Select or type a conversation name and save.
5. Install the CLI from this repository or the release folder:

```bash
bash scripts/install-cli.sh
```

Ensure `~/.local/bin` is on your `PATH`, then:

```bash
chatdrop conversations
chatdrop search --conversation 'Project group' --from 2026-09-01 --to 2026-09-16 --all
chatdrop search 'release' --conversation 'Project group'
chatdrop context '<message-id>' --radius 3
chatdrop attachments '<message-id>'
```

Queries import new receipts automatically. The keyword is optional. Date-only bounds
include both full days. Repeat `--conversation` to query multiple conversations.
Results are paginated by default; `--all` returns all matches.

For example, ask an agent with shell access:

> Use `chatdrop` to read Project group's messages from last week. Summarize the
> decisions and unresolved questions, and include the source message IDs.

ChatDrop itself does not send data to an AI provider. If you ask an external AI tool
to read the archive, that tool's data handling applies.

## Important limits

- The observed WeChat exports contain display names and minute-level timestamps,
  but no stable group or message IDs. Conversation names are **your local labels**.
- Message matching uses conversation, sender, time, body, and available attachment
  evidence. Equal messages within one export remain separate occurrences. Identical
  same-minute messages in separate exports can still be ambiguous.
- Download media in WeChat before exporting it. If an export only contains a media
  reference, ChatDrop reports it as missing; a later matching export can fill it.
- Original files are retained, and no automatic retention/deletion is enabled.
- This first release is ad-hoc signed and is not notarized. macOS may require using
  **System Settings → Privacy & Security → Open Anyway** on first launch.

See [architecture and matching rules](docs/architecture.md) for the exact boundaries.

## Build and test

Requires macOS Command Line Tools, Swift, and Python 3.9+:

```bash
bash scripts/build.sh
python3 -m unittest discover -s tests -v
```

The app is written to `build/ChatDrop.app`; the build targets the build machine's
architecture. The share extension must be installed and enabled to test reception.

Please use synthetic or redacted exports in issues and pull requests. Do not attach
private conversations, database files, or credentials. See [CONTRIBUTING](CONTRIBUTING.md).

## Acknowledgements

[Dukou](https://github.com/qzz0518/Dukou) and [Dihua](https://github.com/ZHlovecat/dihua)
helped demonstrate the usefulness of WeChat's native export and macOS sharing flow.

## License

[MIT](LICENSE).
