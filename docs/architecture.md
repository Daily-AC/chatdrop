# Storage and matching

The native macOS extension copies an explicitly shared ZIP before the item-provider
callback returns. It publishes a receipt only after copying completes. Conversation
selection uses a shared local catalog with stable UUIDs and editable display names.

The CLI imports receipts on demand. It indexes messages in SQLite and keeps original
archives, transcripts, media, and per-batch provenance on disk.

## Paths

- `~/Downloads/ChatDrop/<receipt-id>/archive.zip`: received original
- `~/Downloads/ChatDrop/<receipt-id>/receipt.json`: reception metadata and conversation ID
- `~/Downloads/ChatDrop/conversations.json`: conversation catalog
- `~/Library/Application Support/ChatDrop/chatdrop.sqlite3`: searchable index
- `~/Library/Application Support/ChatDrop/imports/<sha256>/`: retained archive and extracted files

The extension's sandbox Downloads directory resolves to the actual Downloads directory
on the tested Mac. Catalog updates use a cross-process lock and atomic replacement;
SQLite maintains an indexed copy. Private store directories use mode 0700, and the
database, catalog, originals, and extracted files use mode 0600.

## Observed format

The parser currently supports UTF-8 `聊天记录.txt` with a middle-dot sender line, a
Chinese date/time line, and a potentially multiline body. Media references appear as
`[图片] filename.jpg` or equivalent bracketed references, with payloads in separate
ZIP entries. The supplied exports have no stable conversation, sender, or message ID.

## Deduplication

1. A SHA-256 match identifies the same archive, even if its filename changed.
2. Within a manually assigned conversation, messages match by sender display name,
   normalized time, and exact body. Available attachment bytes can reject a match.
3. A message can occur multiple times in one export. Matching retains that multiplicity
   rather than collapsing every equal sender/time/body tuple.
4. A new matching export can replace a missing attachment with an available file.
   An export lacking a file does not remove one already stored.
5. Canonical messages link back to every contributing import. `assign` rebuilds these
   associations transactionally from retained originals when batch ownership changes.

Unassigned batches are not merged across exports. Identical same-minute messages
that only appear in separate exports remain ambiguous. Changes to attachment filenames
also affect exact-body matching. These are source-format limits, not solved identities.

## Import limits

The importer rejects traversal paths, links, filename collisions, and encrypted ZIPs.
Current limits are 2 GiB compressed/expanded size, 10000 entries, and 8 MiB transcript.
Original ZIP/TXT bytes are retained. Message boundary separator newlines are normalized;
internal blank lines, punctuation, and mention spacing are preserved.

Schema 3 includes conversations, canonical messages, import-message links, attachment
origins, and source fingerprints. Upgrading the original schema-1 store creates a
private `chatdrop.pre-conversations.sqlite3` backup alongside it.

## Validation scope

Automated tests cover parsing, Unicode and multiline text, archive rejection without
partial imports, queries and pagination, migration, conversation renaming/reassignment,
partial-export attachment completion, repeated same-minute messages, conflicting media,
multiple conversation filters, and inclusive date/time boundaries.

The macOS share extension was tested with real exports and a native system-sharing
host. The critical media-backfill case was verified with an original export lacking
an MP4 and a later export containing only that matching video message: the conversation
message count remained unchanged and the copied MP4 matched the new ZIP exactly.

Test fixtures in this repository are synthetic. User data is stored outside the repo.
