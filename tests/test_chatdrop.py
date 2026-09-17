import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("chatdrop", ROOT / "cli/chatdrop.py")
chatdrop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chatdrop)
TRANSCRIPT = (ROOT / "tests/fixtures/chat.txt").read_text()


class ChatDropTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "sample.zip"
        self.make_zip(self.archive)

    def make_zip(self, path, transcript=TRANSCRIPT, extra=None):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("聊天记录.txt", transcript)
            archive.writestr("聊天记录内的图片、视频和文件/图片_1.jpg", b"synthetic attachment")
            for name, data in (extra or {}).items():
                archive.writestr(name, data)

    def test_observed_format_preserves_multiline_unicode_and_missing_video(self):
        transcript, messages, attachments, files = chatdrop.read_archive(self.archive)
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[1]["body"], "测试乙 测试丙 请检查附件。")
        self.assertEqual(messages[2]["body"], "第一行\n\n第二行，保留段落。")
        self.assertEqual(messages[0]["sent_at"], "2026-09-10T17:33")
        self.assertEqual([a["status"] for a in attachments], ["present", "missing"])
        self.assertIsNone(attachments[1]["member"])
        self.assertEqual(len(files), 1)

    def test_repeated_zip_is_idempotent_but_overlapping_exports_stay_separate(self):
        with chatdrop.Store(self.root / "store") as store:
            first = store.import_zip(self.archive)
            renamed = self.root / "renamed.zip"
            renamed.write_bytes(self.archive.read_bytes())
            second = store.import_zip(renamed)
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(second["id"], first["id"])
            overlap = self.root / "overlap.zip"
            self.make_zip(overlap, TRANSCRIPT + "\n\n·测试乙\n2026年9月16日 12:00\n另一次导出\n")
            store.import_zip(overlap)
            self.assertEqual(store.db.execute("SELECT count(*) FROM messages").fetchone()[0], 9)
            self.assertEqual(store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
            stored = store.root / "imports" / first["id"] / "archive.zip"
            self.assertEqual(stored.read_bytes(), self.archive.read_bytes())
            self.assertEqual(stat.S_IMODE(stored.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((store.root / "chatdrop.sqlite3").stat().st_mode), 0o600)

    def test_unrecognized_text_and_unsafe_archives_do_not_partially_import(self):
        with chatdrop.Store(self.root / "store") as store:
            for index, extra in enumerate([{"../escape": b"bad"}, {"/absolute": b"bad"}, {"FILE": b"1", "file": b"2"}]):
                bad = self.root / ("bad%d.zip" % index)
                self.make_zip(bad, extra=extra)
                with self.assertRaises(chatdrop.ImportErrorDetail):
                    store.import_zip(bad)
            invalid = self.root / "invalid.zip"
            self.make_zip(invalid, "unrecognized export")
            with self.assertRaises(chatdrop.ImportErrorDetail):
                store.import_zip(invalid)
            linked = self.root / "symlink.zip"
            self.make_zip(linked)
            with zipfile.ZipFile(linked, "a") as archive:
                entry = zipfile.ZipInfo("link")
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(entry, "../outside")
            with self.assertRaises(chatdrop.ImportErrorDetail):
                store.import_zip(linked)
            self.assertEqual(store.db.execute("SELECT count(*) FROM imports").fetchone()[0], 0)
            self.assertEqual(list((store.root / "imports").iterdir()), [])

    def cli(self, *arguments):
        result = subprocess.run(["/usr/bin/python3", str(ROOT / "cli/chatdrop.py"),
                                 "--store", str(self.root / "cli-store"),
                                 "--inbox", str(self.root / "inbox"), *arguments],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def test_cli_auto_sync_search_pagination_context_and_attachment_paths(self):
        receipt_dir = self.root / "inbox" / "received-batch"
        receipt_dir.mkdir(parents=True)
        (receipt_dir / "archive.zip").write_bytes(self.archive.read_bytes())
        (receipt_dir / "receipt.json").write_text(json.dumps({"id": "received-batch", "fileName": "archive.zip", "originalName": "sample.zip"}))
        first = self.cli("stats")
        self.assertEqual(first["data"]["messages"], 4)
        self.assertEqual(first["sync"]["imported"], 1)
        second = self.cli("stats")
        self.assertEqual(second["sync"]["unchanged"], 1)
        self.assertEqual(second["data"]["messages"], 4)
        latest = self.cli("latest")["data"]
        self.assertIsNone(latest["conversation"])
        page = self.cli("messages", "latest", "--limit", "2")["data"]
        self.assertEqual(page["next_offset"], 2)
        next_page = self.cli("messages", latest["id"][:8], "--offset", "2")["data"]
        self.assertEqual([m["ordinal"] for m in next_page["messages"]], [3, 4])
        found = self.cli("search", "段落")["data"]["messages"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["ordinal"], 3)
        self.assertEqual(self.cli("search", "' OR 1=1 --")["data"]["messages"], [])
        nearby = self.cli("context", found[0]["id"], "--radius", "1")["data"]["messages"]
        self.assertEqual([m["ordinal"] for m in nearby], [2, 3, 4])
        image = self.cli("attachments", page["messages"][0]["id"])["data"][0]
        self.assertEqual(Path(image["path"]).read_bytes(), b"synthetic attachment")
        video = nearby[-1]["attachments"][0]
        self.assertEqual(video["status"], "missing")
        self.assertIsNone(video["path"])

    def test_conversation_dedup_fills_video_from_a_partial_export(self):
        conversation = self.cli("conversations", "create", "测试群")["data"]
        initial = self.cli("import", str(self.archive), "--conversation", conversation["id"])["data"]
        before = self.cli("search", "--conversation", "测试群", "--all")["data"]
        self.assertEqual(before["total"], 4)
        video = next(m for m in before["messages"] if "[视频]" in m["body"])
        self.assertEqual(video["attachments"][0]["status"], "missing")
        partial = self.root / "downloaded.zip"
        self.make_zip(partial, "·测试甲\n2026年9月16日 11:41\n[视频] 视频_1.mp4\n",
                      extra={"聊天记录内的图片、视频和文件/视频_1.mp4": b"synthetic downloaded video"})
        imported = self.cli("import", str(partial), "--conversation", "测试群")["data"]
        self.assertEqual(imported["added_messages"], 0)
        self.assertEqual(imported["reused_messages"], 1)
        self.assertEqual(imported["filled_attachments"], 1)
        after = self.cli("search", "--conversation", conversation["id"], "--all")["data"]
        self.assertEqual(after["total"], 4)
        updated = next(m for m in after["messages"] if m["id"] == video["id"])
        self.assertEqual(len(updated["source_import_ids"]), 2)
        self.assertEqual(Path(updated["attachments"][0]["path"]).read_bytes(), b"synthetic downloaded video")
        self.assertEqual(self.cli("messages", imported["id"])["data"]["messages"][0]["id"], video["id"])
        self.assertEqual(self.cli("import", str(self.archive), "--conversation", "测试群")["data"]["status"], "duplicate")
        self.assertEqual(self.cli("stats")["data"]["missing_attachments"], 0)
        renamed = self.cli("conversations", "rename", conversation["id"], "测试群新名")["data"]
        self.assertEqual(renamed["id"], conversation["id"])
        self.assertEqual(self.cli("search", "--conversation", "测试群新名", "--all")["data"]["total"], 4)
        other = self.cli("conversations", "create", "另一个群")["data"]
        self.cli("assign", imported["id"], "--conversation", other["id"])
        self.assertEqual(self.cli("stats")["data"]["messages"], 5)
        self.cli("assign", imported["id"], "--conversation", conversation["id"])
        self.assertEqual(self.cli("stats")["data"]["messages"], 4)

    def test_same_minute_repeated_messages_and_different_media_are_preserved(self):
        conversation = self.cli("conversations", "create", "重复消息群")["data"]
        record = "·测试甲\n2026年9月16日 12:00\n收到\n"
        repeated = self.root / "repeated.zip"
        self.make_zip(repeated, record + "\n" + record)
        self.cli("import", str(repeated), "--conversation", conversation["id"])
        single = self.root / "single.zip"
        self.make_zip(single, record)
        self.cli("import", str(single), "--conversation", conversation["id"])
        self.assertEqual(self.cli("search", "--conversation", conversation["id"], "--all")["data"]["total"], 2)
        for index in range(2):
            image = self.root / ("image%d.zip" % index)
            with zipfile.ZipFile(image, "w") as archive:
                archive.writestr("聊天记录.txt", "·测试甲\n2026年9月16日 12:00\n[图片] 同名.jpg\n")
                archive.writestr("同名.jpg", bytes([index]))
            self.cli("import", str(image), "--conversation", conversation["id"])
        self.assertEqual(self.cli("search", "--conversation", conversation["id"], "--all")["data"]["total"], 4)

    def test_multiple_conversations_time_boundaries_and_complete_results(self):
        names = ["群 A", "群 B", "群 C"]
        ids = [self.cli("conversations", "create", name)["data"]["id"] for name in names]
        for index, conversation_id in enumerate(ids):
            archive = self.root / ("range%d.zip" % index)
            body = "\n\n".join("·测试甲\n%s\n消息 %d-%d" % (date, index, n) for n, date in enumerate([
                "2026年9月15日 23:59", "2026年9月16日 00:00", "2026年9月16日 23:59", "2026年9月17日 00:00"]))
            self.make_zip(archive, body)
            self.cli("import", str(archive), "--conversation", conversation_id)
        result = self.cli("search", "--conversation", "群 A", "--conversation", ids[1],
                          "--from", "2026-09-16", "--to", "2026-09-16", "--all")["data"]
        self.assertEqual(result["total"], 4)
        self.assertEqual({m["conversation"]["id"] for m in result["messages"]}, set(ids[:2]))
        minute = self.cli("search", "--conversation", ids[0], "--from", "2026-09-16 23:59", "--to", "2026-09-16 23:59", "--all")["data"]
        self.assertEqual(minute["total"], 1)
        big = self.root / "big.zip"
        self.make_zip(big, "\n\n".join("·测试甲\n2026年9月16日 12:00\n长列表-%d" % n for n in range(205)))
        self.cli("import", str(big), "--conversation", ids[0])
        page = self.cli("search", "长列表", "--conversation", ids[0])["data"]
        self.assertEqual((page["total"], page["returned"], page["next_offset"]), (205, 50, 50))
        all_rows = self.cli("search", "长列表", "--conversation", ids[0], "--all")["data"]
        self.assertEqual(all_rows["returned"], 205)
        self.assertIsNone(all_rows["next_offset"])
        listing = self.cli("conversations")["data"]["conversations"]
        self.assertEqual(next(c for c in listing if c["id"] == ids[0])["messages"], 209)
        for arguments in [("search", "--conversation", "不存在"),
                          ("search", "--from", "2026-09-18", "--to", "2026-09-16"),
                          ("search", "--to", "2026-02-30"),
                          ("search", "--all", "--offset", "1")]:
            result = subprocess.run(["/usr/bin/python3", str(ROOT / "cli/chatdrop.py"),
                                     "--store", str(self.root / "cli-store"), "--inbox", str(self.root / "inbox"), *arguments], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("error", json.loads(result.stderr))

    def install_cli(self, home):
        return subprocess.run(["/bin/bash", str(ROOT / "scripts/install-cli.sh")],
                              text=True, capture_output=True,
                              env={**os.environ, "HOME": str(home)})

    def test_installer_links_the_skill_only_into_agent_homes_that_exist(self):
        home = self.root / "home"
        (home / ".claude").mkdir(parents=True)
        result = self.install_cli(home)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue((home / ".local/bin/chatdrop").is_symlink())
        skill = home / ".claude/skills/chatdrop/SKILL.md"
        self.assertTrue(skill.is_file())
        self.assertEqual(skill.read_text().splitlines()[0], "---")
        self.assertFalse((home / ".codex").exists())
        self.assertIn(str(home / ".claude/skills/chatdrop"), result.stdout.splitlines())

    def test_installer_refuses_to_replace_an_unrelated_skill(self):
        home = self.root / "occupied"
        (home / ".claude/skills/chatdrop").mkdir(parents=True)
        result = self.install_cli(home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing", result.stderr)

    def test_v1_database_migration_preserves_existing_records(self):
        root = self.root / "legacy"
        root.mkdir()
        with sqlite3.connect(root / "chatdrop.sqlite3") as database:
            database.executescript(chatdrop.SCHEMA)
            database.execute("PRAGMA user_version=1")
            database.execute("INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             ("a" * 64, "2026-09-16", "old.zip", "聊天记录.txt", 1, 0, 0, "[]"))
            database.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             ("a" * 64 + ":1", "a" * 64, 1, "测试甲", "2026-09-16T12:00", "2026年9月16日 12:00", "原消息", 1))
        with chatdrop.Store(root) as store:
            self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(store.db.execute("SELECT body FROM messages").fetchone()[0], "原消息")
            self.assertEqual(store.db.execute("SELECT count(*) FROM import_messages").fetchone()[0], 1)
            self.assertEqual(store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertTrue((root / "chatdrop.pre-conversations.sqlite3").is_file())


if __name__ == "__main__":
    unittest.main()
