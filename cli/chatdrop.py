#!/usr/bin/env python3
"""Local WeChat export ingestion and JSON queries. Python standard library only."""
import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import unicodedata
import uuid
import zipfile

DATE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日 (\d{2}):(\d{2})(?::(\d{2}))?$")
REFERENCE = re.compile(r"^\[([^\]\r\n]+)\]\s+([^\r\n]+)$", re.MULTILINE)
MAX_BYTES = 2 * 1024**3
MAX_TEXT_BYTES = 8 * 1024**2


class ImportErrorDetail(ValueError):
    pass


def now_string():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Conversations:
    """Shared catalog for the sandboxed extension and CLI; SQLite indexes this file."""
    def __init__(self, inbox):
        self.root = Path(inbox).expanduser()

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(self.root / ".conversations.lock", "a") as lock:
            os.chmod(self.root / ".conversations.lock", 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / "conversations.json"
            catalog = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schemaVersion": 1, "conversations": []}
            if catalog.get("schemaVersion") != 1 or not isinstance(catalog.get("conversations"), list):
                raise ImportErrorDetail("会话目录格式无效。")
            yield catalog

    def all(self):
        with self.locked() as catalog:
            return list(catalog["conversations"])

    def save(self, catalog):
        descriptor, name = tempfile.mkstemp(prefix=".conversations-", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(catalog, output, ensure_ascii=False, indent=2)
            os.replace(name, self.root / "conversations.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def find(items, value):
        exact = [item for item in items if item["id"] == value]
        if exact:
            return exact[0]
        named = [item for item in items if item["name"] == unicodedata.normalize("NFC", value.strip())]
        if len(named) == 1:
            return named[0]
        if not named and len(value) >= 8:
            matches = [item for item in items if item["id"].startswith(value)]
            if len(matches) == 1:
                return matches[0]
        raise ImportErrorDetail("找不到唯一会话，请运行 chatdrop conversations 并使用会话 ID。")

    def change(self, name, selector=None):
        name = unicodedata.normalize("NFC", name.strip())
        if not name or len(name) > 120 or any(c in name for c in "\n\r\x00"):
            raise ImportErrorDetail("会话名须为 1–120 个字符，不能包含换行。")
        with self.locked() as catalog:
            if selector is None:
                item = {"id": str(uuid.uuid4()), "name": name, "createdAt": now_string(),
                        "updatedAt": now_string(), "lastUsedAt": now_string()}
                catalog["conversations"].append(item)
            else:
                item = self.find(catalog["conversations"], selector)
                item.update(name=name, updatedAt=now_string())
            self.save(catalog)
            return item


def parse_transcript(text):
    """Parse the observed middle-dot sender / Chinese date / multiline body format.

    Timestamps are local wall-clock values. The export does not provide a timezone,
    conversation identifier, or stable sender/message identifiers.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    starts = [i for i in range(len(lines) - 1)
              if lines[i].startswith("·") and len(lines[i]) > 1 and DATE.fullmatch(lines[i + 1])]
    if not starts or any(line.strip() for line in lines[:starts[0]]):
        raise ImportErrorDetail("无法识别聊天记录格式；原 ZIP 保留在收件箱。")
    messages = []
    for ordinal, start in enumerate(starts, 1):
        end = starts[ordinal] if ordinal < len(starts) else len(lines)
        match = DATE.fullmatch(lines[start + 1])
        values = [int(value or 0) for value in match.groups()]
        try:
            timestamp = dt.datetime(*values)
        except ValueError as error:
            raise ImportErrorDetail("聊天记录第 %d 行的时间无效。" % (start + 2)) from error
        body = "\n".join(lines[start + 2:end]).strip("\n")
        messages.append({
            "ordinal": ordinal, "sender": lines[start][1:],
            "sent_at": timestamp.isoformat(timespec="seconds" if match.group(6) else "minutes"),
            "timestamp_raw": lines[start + 1], "body": body,
            "source_line": start + 1,
        })
    return messages


def archive_members(archive):
    infos = archive.infolist()
    if len(infos) > 10000 or sum(info.file_size for info in infos) > MAX_BYTES:
        raise ImportErrorDetail("ZIP 超出当前上限：10000 个条目或 2 GiB 解压大小。")
    members, seen = [], set()
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        file_type = stat.S_IFMT(info.external_attr >> 16)
        if (path.is_absolute() or ".." in path.parts or "\\" in name or "\x00" in name
                or not path.parts or file_type not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ImportErrorDetail("ZIP 包含不安全的路径或链接。")
        key = unicodedata.normalize("NFC", str(path)).casefold()
        if key in seen:
            raise ImportErrorDetail("ZIP 包含重名或大小写冲突的路径。")
        seen.add(key)
        if info.flag_bits & 1:
            raise ImportErrorDetail("暂不支持加密 ZIP。")
        members.append((info, str(path)))
    return members


def read_archive(path):
    with zipfile.ZipFile(path) as archive:
        members = archive_members(archive)
        transcripts = [(info, name) for info, name in members
                       if not info.is_dir() and PurePosixPath(name).name == "聊天记录.txt"]
        if len(transcripts) != 1:
            raise ImportErrorDetail("ZIP 必须包含且仅包含一份“聊天记录.txt”。")
        info, transcript_name = transcripts[0]
        if info.file_size > MAX_TEXT_BYTES:
            raise ImportErrorDetail("聊天文本超过当前 8 MiB 上限。")
        try:
            messages = parse_transcript(archive.read(info).decode("utf-8-sig"))
        except UnicodeDecodeError as error:
            raise ImportErrorDetail("聊天文本不是 UTF-8，尚未支持此格式。") from error
        files = [name for info, name in members if not info.is_dir() and name != transcript_name]
        references = []
        for message in messages:
            for position, (kind, name) in enumerate(REFERENCE.findall(message["body"]), 1):
                matches = [member for member in files if PurePosixPath(member).name == name]
                status = "present" if len(matches) == 1 else "missing" if not matches else "ambiguous"
                references.append({"ordinal": message["ordinal"], "position": position,
                                   "kind": kind, "name": name, "status": status,
                                   "member": matches[0] if status == "present" else None})
        return transcript_name, messages, references, files


SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, original_name TEXT NOT NULL,
    transcript_member TEXT NOT NULL, message_count INTEGER NOT NULL,
    file_count INTEGER NOT NULL, missing_count INTEGER NOT NULL, files_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id),
    ordinal INTEGER NOT NULL, sender TEXT NOT NULL, sent_at TEXT NOT NULL,
    timestamp_raw TEXT NOT NULL, body TEXT NOT NULL, source_line INTEGER NOT NULL,
    UNIQUE(import_id, ordinal)
);
CREATE INDEX IF NOT EXISTS messages_sender ON messages(sender);
CREATE INDEX IF NOT EXISTS messages_time ON messages(sent_at);
CREATE TABLE IF NOT EXISTS attachments (
    message_id TEXT NOT NULL REFERENCES messages(id), position INTEGER NOT NULL,
    kind TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, member TEXT,
    PRIMARY KEY(message_id, position)
);
CREATE TABLE IF NOT EXISTS sources (
    path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
    import_id TEXT NOT NULL REFERENCES imports(id)
);
"""


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.lock = open(self.root / ".lock", "a")
        os.chmod(self.root / ".lock", 0o600)
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.db = sqlite3.connect(str(self.root / "chatdrop.sqlite3"))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3):
            self.db.close()
            self.lock.close()
            raise ImportErrorDetail("数据库版本较新，请更新 ChatDrop CLI。")
        self.db.executescript(SCHEMA)
        if version == 1:
            backup_path = self.root / "chatdrop.pre-conversations.sqlite3"
            if not backup_path.exists():
                with sqlite3.connect(str(backup_path)) as backup:
                    self.db.backup(backup)
                os.chmod(backup_path, 0o600)
        if version < 2:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_used_at TEXT NOT NULL)")
                self.db.execute("ALTER TABLE imports ADD COLUMN conversation_id TEXT REFERENCES conversations(id)")
                self.db.execute("ALTER TABLE sources ADD COLUMN declared_conversation_id TEXT")
                self.db.execute("CREATE INDEX imports_conversation ON imports(conversation_id)")
                self.db.execute("PRAGMA user_version=2")
        if version < 3:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("ALTER TABLE messages ADD COLUMN conversation_id TEXT REFERENCES conversations(id)")
                self.db.execute("ALTER TABLE messages ADD COLUMN fingerprint TEXT")
                self.db.execute("CREATE INDEX messages_conversation_fingerprint ON messages(conversation_id, fingerprint)")
                self.db.execute("ALTER TABLE attachments ADD COLUMN asset_import_id TEXT REFERENCES imports(id)")
                self.db.execute("UPDATE attachments SET asset_import_id=(SELECT import_id FROM messages WHERE id=message_id)")
                self.db.execute("""CREATE TABLE import_messages (
                    import_id TEXT NOT NULL REFERENCES imports(id), ordinal INTEGER NOT NULL,
                    message_id TEXT NOT NULL REFERENCES messages(id), source_line INTEGER NOT NULL,
                    sender TEXT NOT NULL, timestamp_raw TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(import_id, ordinal))""")
                self.db.execute("CREATE INDEX import_messages_message ON import_messages(message_id)")
                self.db.execute("INSERT INTO import_messages SELECT import_id, ordinal, id, source_line, sender, timestamp_raw, body FROM messages")
                for row in self.db.execute("SELECT * FROM messages").fetchall():
                    self.db.execute("UPDATE messages SET conversation_id=(SELECT conversation_id FROM imports WHERE id=?), fingerprint=? WHERE id=?",
                                    (row["import_id"], self.fingerprint(row), row["id"]))
                self.db.execute("PRAGMA user_version=3")
        os.chmod(self.root / "chatdrop.sqlite3", 0o600)
        (self.root / "imports").mkdir(exist_ok=True, mode=0o700)
        return self

    def __exit__(self, *args):
        self.db.close()
        self.lock.close()

    def update_conversations(self, items):
        with self.db:
            for item in items:
                uuid.UUID(item["id"])
                self.db.execute("""INSERT INTO conversations VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at,
                    last_used_at=excluded.last_used_at""", (item["id"], item["name"], item["createdAt"], item["updatedAt"], item["lastUsedAt"]))

    def resolve_conversation(self, value):
        return Conversations.find([dict(row) for row in self.db.execute("SELECT id, name FROM conversations")], value)["id"]

    def assign(self, import_id, conversation_id, overwrite=False):
        row = self.db.execute("SELECT conversation_id FROM imports WHERE id=?", (import_id,)).fetchone()
        if row is None:
            raise ImportErrorDetail("导入批次不存在。")
        if not overwrite and row[0] is not None and row[0] != conversation_id:
            raise ImportErrorDetail("同一 ZIP 已归入另一个会话；如需更正，请使用 chatdrop assign。")
        if row[0] != conversation_id:
            self.db.execute("UPDATE imports SET conversation_id=? WHERE id=?", (conversation_id, import_id))
            self.rebuild_messages()

    @staticmethod
    def fingerprint(message):
        values = [message["sender"], dt.datetime.fromisoformat(message["sent_at"]).isoformat(timespec="seconds"), message["body"]]
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()

    def asset_path(self, import_id, member):
        return self.root / "imports" / import_id / "files" / member if import_id and member else None

    @staticmethod
    def file_digest(path):
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.digest()

    def compatible_attachments(self, message_id, import_id, references):
        old = {row["position"]: row for row in self.db.execute("SELECT * FROM attachments WHERE message_id=?", (message_id,))}
        for ref in references:
            previous = old.get(ref["position"])
            if previous and previous["status"] == "present" and ref["status"] == "present":
                old_path = self.asset_path(previous["asset_import_id"], previous["member"])
                new_path = self.asset_path(import_id, ref["member"])
                if old_path and old_path.is_file() and self.file_digest(old_path) != self.file_digest(new_path):
                    return False
        return True

    def ingest_messages(self, import_id, messages, references):
        conversation_id = self.db.execute("SELECT conversation_id FROM imports WHERE id=?", (import_id,)).fetchone()[0]
        claimed = set()
        result = {"added_messages": 0, "reused_messages": 0, "filled_attachments": 0}
        for message in messages:
            fingerprint = self.fingerprint(message)
            refs = [ref for ref in references if ref["ordinal"] == message["ordinal"]]
            candidates = self.db.execute("SELECT id FROM messages WHERE conversation_id=? AND fingerprint=? ORDER BY rowid",
                                         (conversation_id, fingerprint)).fetchall() if conversation_id else []
            message_id = next((row["id"] for row in candidates if row["id"] not in claimed
                               and self.compatible_attachments(row["id"], import_id, refs)), None)
            if message_id is None:
                message_id = import_id + ":" + str(message["ordinal"])
                self.db.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                    message_id, import_id, message["ordinal"], message["sender"], message["sent_at"],
                    message["timestamp_raw"], message["body"], message["source_line"], conversation_id, fingerprint))
                result["added_messages"] += 1
            else:
                result["reused_messages"] += 1
            claimed.add(message_id)
            self.db.execute("INSERT INTO import_messages VALUES (?, ?, ?, ?, ?, ?, ?)", (
                import_id, message["ordinal"], message_id, message["source_line"], message["sender"], message["timestamp_raw"], message["body"]))
            for ref in refs:
                previous = self.db.execute("SELECT * FROM attachments WHERE message_id=? AND position=?", (message_id, ref["position"])).fetchone()
                old_path = self.asset_path(previous["asset_import_id"], previous["member"]) if previous else None
                should_fill = previous is not None and ref["status"] == "present" and (previous["status"] != "present" or not old_path or not old_path.is_file())
                if previous is None or should_fill:
                    self.db.execute("INSERT OR REPLACE INTO attachments VALUES (?, ?, ?, ?, ?, ?, ?)", (
                        message_id, ref["position"], ref["kind"], ref["name"], ref["status"], ref["member"], import_id))
                    if should_fill:
                        result["filled_attachments"] += 1
        return result

    def rebuild_messages(self):
        # Explicit reassignment is rare. Reindex retained originals in one transaction
        # so splitting or merging a conversation never leaves stale deduplication links.
        self.db.execute("DELETE FROM attachments")
        self.db.execute("DELETE FROM import_messages")
        self.db.execute("DELETE FROM messages")
        for row in self.db.execute("SELECT id FROM imports ORDER BY imported_at, id").fetchall():
            _, messages, references, _ = read_archive(self.root / "imports" / row["id"] / "archive.zip")
            self.ingest_messages(row["id"], messages, references)

    def import_zip(self, source, original_name=None, cached=False, conversation_id=None):
        if conversation_id and not self.db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
            raise ImportErrorDetail("收件记录指定的会话不存在。")
        source = Path(source).expanduser().resolve(strict=True)
        before = source.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise ImportErrorDetail("来源必须是大小不超过 2 GiB 的 ZIP 文件。")
        previous = self.db.execute("SELECT * FROM sources WHERE path=?", (str(source),)).fetchone()
        if (cached and previous and (previous["size"], previous["mtime_ns"]) == (before.st_size, before.st_mtime_ns)
                and previous["declared_conversation_id"] == conversation_id):
            return {"status": "unchanged", "id": previous["import_id"]}
        # Snapshot first, so the digest, parser, and retained archive use identical bytes.
        with tempfile.TemporaryDirectory(prefix=".import-", dir=self.root) as temporary:
            stage = Path(temporary)
            snapshot = stage / "archive.zip"
            digest = hashlib.sha256()
            with source.open("rb") as incoming, snapshot.open("xb") as output:
                total = 0
                for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ImportErrorDetail("ZIP 超过 2 GiB 上限。")
                    digest.update(chunk)
                    output.write(chunk)
            os.chmod(snapshot, 0o600)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ImportErrorDetail("复制期间来源文件发生变化，请重试。")
            import_id = digest.hexdigest()
            source_values = (str(source), before.st_size, before.st_mtime_ns, import_id, conversation_id)
            if self.db.execute("SELECT 1 FROM imports WHERE id=?", (import_id,)).fetchone():
                with self.db:
                    if conversation_id:
                        self.assign(import_id, conversation_id)
                    self.db.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?)", source_values)
                return {"status": "duplicate", "id": import_id}
            transcript, messages, references, files = read_archive(snapshot)
            content = stage / "files"
            content.mkdir(mode=0o700)
            with zipfile.ZipFile(snapshot) as archive:
                for info, member in archive_members(archive):
                    target = content / member
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with archive.open(info) as incoming, target.open("xb") as output:
                        shutil.copyfileobj(incoming, output, 1024 * 1024)
                    os.chmod(target, 0o600)
            destination = self.root / "imports" / import_id
            # Only an uncommitted generated directory can exist without an imports row.
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(str(stage), str(destination))
            try:
                with self.db:
                    self.db.execute("INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                        import_id, dt.datetime.now(dt.timezone.utc).isoformat(), original_name or source.name,
                        transcript, len(messages), len(files),
                        sum(ref["status"] != "present" for ref in references),
                        json.dumps(files, ensure_ascii=False), conversation_id))
                    indexed = self.ingest_messages(import_id, messages, references)
                    self.db.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?)", source_values)
            except BaseException:
                shutil.rmtree(destination)
                raise
        return {"status": "imported", "id": import_id, "messages": len(messages),
                "files": len(files), "missing_attachments_in_source": sum(r["status"] != "present" for r in references), **indexed}

    def sync(self, inbox):
        result = {"imported": 0, "duplicate": 0, "unchanged": 0, "added_messages": 0,
                  "reused_messages": 0, "filled_attachments": 0, "errors": []}
        inbox = Path(inbox).expanduser()
        if not inbox.exists():
            return result
        for receipt_path in sorted(inbox.glob("*/receipt.json")):
            if receipt_path.parent.name.startswith("."):
                continue
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt.get("fileName") != "archive.zip" or receipt.get("id") != receipt_path.parent.name:
                    raise ImportErrorDetail("无效的收件记录。")
                record = self.import_zip(receipt_path.parent / "archive.zip", receipt.get("originalName"),
                                         cached=True, conversation_id=receipt.get("conversationID"))
                result[record["status"]] += 1
                for key in ("added_messages", "reused_messages", "filled_attachments"):
                    result[key] += record.get(key, 0)
            except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
                result["errors"].append({"receipt": str(receipt_path), "error": str(error)})
        return result

    def import_record(self, row):
        record = dict(row)
        record["missing_attachments_in_original"] = record.pop("missing_count")
        directory = self.root / "imports" / record["id"]
        files = json.loads(record.pop("files_json"))
        record.update({"archive_path": str(directory / "archive.zip"),
                       "transcript_path": str(directory / "files" / record["transcript_member"]),
                       "files": [str(directory / "files" / name) for name in files],
                       "conversation": self.conversation(record.get("conversation_id")), "timestamp_timezone": None})
        return record

    def conversation(self, conversation_id):
        if not conversation_id:
            return None
        row = self.db.execute("SELECT id, name FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        return dict(row) if row else None

    def resolve_import(self, value):
        if value == "latest":
            row = self.db.execute("SELECT id FROM imports ORDER BY imported_at DESC, id DESC LIMIT 1").fetchone()
            if row:
                return row["id"]
        elif re.fullmatch(r"[0-9a-f]{8,64}", value):
            rows = self.db.execute("SELECT id FROM imports WHERE id LIKE ?", (value + "%",)).fetchall()
            if len(rows) == 1:
                return rows[0]["id"]
        raise ImportErrorDetail("找不到唯一的导入批次，请运行 chatdrop imports 获取 ID。")

    def attachment_records(self, message_id):
        records = []
        for row in self.db.execute("SELECT * FROM attachments WHERE message_id=? ORDER BY position", (message_id,)):
            record = dict(row)
            member = record.pop("member")
            record["path"] = str(self.asset_path(record["asset_import_id"], member)) if member else None
            records.append(record)
        return records

    def message_record(self, row):
        record = dict(row)
        for name in ("ordinal", "source_line", "import_id", "sender", "timestamp_raw", "body"):
            if "source_" + name in record:
                record[name] = record.pop("source_" + name)
        record.pop("fingerprint", None)
        record["conversation"] = self.conversation(record["conversation_id"])
        record["source_import_ids"] = [row[0] for row in self.db.execute("SELECT import_id FROM import_messages WHERE message_id=? ORDER BY import_id", (record["id"],))]
        record["attachments"] = self.attachment_records(record["id"])
        return record

    def resolve_message(self, value):
        row = self.db.execute("SELECT * FROM messages WHERE id=?", (value,)).fetchone()
        if row is None:
            parts = value.rsplit(":", 1)
            if len(parts) == 2 and parts[1].isdigit():
                row = self.db.execute("SELECT m.* FROM import_messages s JOIN messages m ON m.id=s.message_id WHERE s.import_id=? AND s.ordinal=?",
                                      (parts[0], int(parts[1]))).fetchone()
        if row is None:
            raise ImportErrorDetail("找不到消息 ID。请从 messages 或 search 结果中获取。")
        return row


def bounded_int(value):
    value = int(value)
    if not 1 <= value <= 200:
        raise argparse.ArgumentTypeError("必须在 1 到 200 之间")
    return value


def nonnegative(value):
    value = int(value)
    if value < 0:
        raise argparse.ArgumentTypeError("必须大于等于 0")
    return value


def time_boundary(value, upper=False):
    if value is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?", value):
        raise ImportErrorDetail("时间须为 YYYY-MM-DD、YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS，不含时区。")
    try:
        instant = dt.datetime.fromisoformat(value)
        if upper:
            instant += dt.timedelta(days=1) if len(value) == 10 else dt.timedelta(minutes=1) if len(value) == 16 else dt.timedelta(seconds=1)
        return instant.isoformat(sep=" ", timespec="seconds")
    except (ValueError, OverflowError) as error:
        raise ImportErrorDetail("日期或时间无效。") from error


def parser():
    cli = argparse.ArgumentParser(description="ChatDrop：微信共享 ZIP 的本地 SQLite 收件箱。输出 JSON；查询前自动导入新收到的 ZIP。")
    cli.add_argument("--store", type=Path, default=Path.home() / "Library/Application Support/ChatDrop")
    cli.add_argument("--inbox", type=Path, default=Path.home() / "Downloads/ChatDrop")
    sub = cli.add_subparsers(dest="command", required=True)
    sub.add_parser("sync", help="导入共享收件箱里的新增 ZIP")
    command = sub.add_parser("import", help="导入指定 ZIP；相同 ZIP 不重复入库")
    command.add_argument("archive", type=Path)
    command.add_argument("--conversation", help="归入已存在的会话名称或 ID")
    sub.add_parser("stats", help="查看批次、消息和附件数量")
    sub.add_parser("latest", help="查看最近入库批次及原始文件路径")
    command = sub.add_parser("conversations", help="列出现有会话、消息数量和时间范围；也可 create / rename")
    actions = command.add_subparsers(dest="conversation_action")
    create = actions.add_parser("create", help="新建会话，生成独立 ID")
    create.add_argument("name")
    rename = actions.add_parser("rename", help="修改显示名称，历史归属不变")
    rename.add_argument("conversation")
    rename.add_argument("name")
    command = sub.add_parser("assign", help="设置或更正已有批次的会话归属")
    command.add_argument("import_id")
    command.add_argument("--conversation", required=True, help="已有会话名称或 ID")
    for name, help_text in [("imports", "列出导入批次"), ("messages", "读取某批次消息"), ("search", "按中文或其他文本子串搜索消息")]:
        command = sub.add_parser(name, help=help_text)
        pagination = command.add_mutually_exclusive_group()
        pagination.add_argument("--limit", type=bounded_int, default=50)
        pagination.add_argument("--all", action="store_true", help="返回全部匹配记录，不分页")
        command.add_argument("--offset", type=nonnegative, default=0)
        if name == "messages":
            command.add_argument("import_id", help="批次 ID、至少 8 位的唯一前缀，或 latest")
        elif name == "search":
            command.add_argument("query", nargs="?", help="可省略关键词，读取所选范围内的全部消息")
            command.add_argument("--sender", help="精确匹配导出的发送者显示名")
            command.add_argument("--import-id", help="只搜索指定批次")
            command.add_argument("--conversation", action="append", default=[], help="会话名称或 ID，可重复指定多个")
            command.add_argument("--from", dest="since", help="消息发送时间起点，包含该时刻")
            command.add_argument("--to", dest="until", help="消息发送时间终点；日期包含整天，分钟/秒包含该单位")
    command = sub.add_parser("context", help="读取消息在同一导出批次中的前后文")
    command.add_argument("message_id")
    command.add_argument("--radius", type=bounded_int, default=3)
    command = sub.add_parser("attachments", help="获取消息附件路径和缺失状态")
    command.add_argument("message_id")
    return cli


def run(args):
    if getattr(args, "all", False) and getattr(args, "offset", 0):
        raise ImportErrorDetail("--all 不能与 --offset 同时使用。")
    since = time_boundary(getattr(args, "since", None))
    until = time_boundary(getattr(args, "until", None), upper=True)
    if since and until and since >= until:
        raise ImportErrorDetail("时间起点不能晚于终点。")
    catalog = Conversations(args.inbox)
    with Store(args.store) as store:
        store.update_conversations(catalog.all())
        if args.command == "import":
            conversation_id = store.resolve_conversation(args.conversation) if args.conversation else None
            return {"data": store.import_zip(args.archive, conversation_id=conversation_id)}
        sync = store.sync(args.inbox)
        if args.command == "sync":
            return {"data": sync}
        if args.command == "conversations":
            if args.conversation_action in ("create", "rename"):
                data = catalog.change(args.name, args.conversation if args.conversation_action == "rename" else None)
                store.update_conversations(catalog.all())
            else:
                rows = store.db.execute("""SELECT c.id, c.name, c.created_at, c.last_used_at,
                    count(i.id) AS imports,
                    (SELECT count(*) FROM messages WHERE conversation_id=c.id) AS messages,
                    (SELECT min(sent_at) FROM messages WHERE conversation_id=c.id) AS first_message_at,
                    (SELECT max(sent_at) FROM messages WHERE conversation_id=c.id) AS last_message_at
                    FROM conversations c LEFT JOIN imports i ON i.conversation_id=c.id
                    GROUP BY c.id ORDER BY c.last_used_at DESC, c.id""").fetchall()
                unassigned = store.db.execute("SELECT count(*) AS imports, coalesce(sum(message_count), 0) AS messages FROM imports WHERE conversation_id IS NULL").fetchone()
                data = {"conversations": [dict(row) for row in rows], "unassigned": dict(unassigned)}
        elif args.command == "assign":
            import_id = store.resolve_import(args.import_id)
            conversation_id = store.resolve_conversation(args.conversation)
            with store.db:
                store.assign(import_id, conversation_id, overwrite=True)
            data = store.import_record(store.db.execute("SELECT * FROM imports WHERE id=?", (import_id,)).fetchone())
        elif args.command == "stats":
            data = {"database": str(store.root / "chatdrop.sqlite3"),
                    "conversations": store.db.execute("SELECT count(*) FROM conversations").fetchone()[0],
                    "imports": store.db.execute("SELECT count(*) FROM imports").fetchone()[0],
                    "messages": store.db.execute("SELECT count(*) FROM messages").fetchone()[0],
                    "attachment_references": store.db.execute("SELECT count(*) FROM attachments").fetchone()[0],
                    "missing_attachments": store.db.execute("SELECT count(*) FROM attachments WHERE status!='present'").fetchone()[0]}
        elif args.command == "latest":
            row = store.db.execute("SELECT * FROM imports ORDER BY imported_at DESC, id DESC LIMIT 1").fetchone()
            data = store.import_record(row) if row else None
        elif args.command == "imports":
            total = store.db.execute("SELECT count(*) FROM imports").fetchone()[0]
            rows = store.db.execute("SELECT * FROM imports ORDER BY imported_at DESC, id DESC LIMIT ? OFFSET ?",
                                    (-1 if args.all else args.limit, args.offset)).fetchall()
            data = {"imports": [store.import_record(row) for row in rows], "total": total,
                    "returned": len(rows), "next_offset": args.offset + len(rows) if args.offset + len(rows) < total else None}
        elif args.command in ("messages", "search"):
            where, values = [], []
            if args.command == "messages":
                where.append("s.import_id=?")
                values.append(store.resolve_import(args.import_id))
                order = "s.ordinal"
            else:
                if args.query == "":
                    raise ImportErrorDetail("搜索词不能为空。")
                if args.query is not None:
                    where.append("instr(m.body, ?) > 0")
                    values.append(args.query)
                if args.sender:
                    where.append("m.sender=?")
                    values.append(args.sender)
                if args.import_id:
                    where.append("m.id IN (SELECT message_id FROM import_messages WHERE import_id=?)")
                    values.append(store.resolve_import(args.import_id))
                if args.conversation:
                    ids = sorted(set(store.resolve_conversation(value) for value in args.conversation))
                    where.append("m.conversation_id IN (" + ",".join("?" for _ in ids) + ")")
                    values.extend(ids)
                if since:
                    where.append("datetime(m.sent_at)>=?")
                    values.append(since)
                if until:
                    where.append("datetime(m.sent_at)<?")
                    values.append(until)
                order = "datetime(m.sent_at), i.imported_at, m.ordinal, m.id"
            condition = " AND ".join(where) or "1"
            tables = " FROM messages m JOIN imports i ON i.id=m.import_id "
            selection = "m.*"
            if args.command == "messages":
                tables += "JOIN import_messages s ON s.message_id=m.id "
                selection += ", " + ", ".join("s." + name + " AS source_" + name for name in ("ordinal", "source_line", "import_id", "sender", "timestamp_raw", "body"))
            tables += "WHERE "
            total = store.db.execute("SELECT count(*)" + tables + condition, values).fetchone()[0]
            rows = store.db.execute("SELECT " + selection + tables + condition + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                                    values + [-1 if args.all else args.limit, args.offset]).fetchall()
            data = {"messages": [store.message_record(row) for row in rows], "total": total,
                    "returned": len(rows), "next_offset": args.offset + len(rows) if args.offset + len(rows) < total else None}
        else:
            row = store.resolve_message(args.message_id)
            if args.command == "attachments":
                data = store.attachment_records(row["id"])
            else:
                rows = store.db.execute("SELECT m.* FROM import_messages s JOIN messages m ON m.id=s.message_id WHERE s.import_id=? AND s.ordinal BETWEEN ? AND ? ORDER BY s.ordinal",
                                        (row["import_id"], row["ordinal"] - args.radius, row["ordinal"] + args.radius)).fetchall()
                data = {"messages": [store.message_record(item) for item in rows]}
        return {"data": data, "sync": sync}


def main():
    os.umask(0o077)
    args = parser().parse_args()
    try:
        result = run(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        errors = result["data"].get("errors", []) if args.command == "sync" else result.get("sync", {}).get("errors", [])
        return 1 if errors else 0
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
