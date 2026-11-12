"""Adding items, merging them, and the pending-sync flag. Uses a throwaway data directory."""
import json, os, pathlib, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from today_board import store


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name)
        self.old = store.HOME
        store.HOME = self.home

    def tearDown(self):
        store.HOME = self.old
        self.tmp.cleanup()

    def write_config(self, **extra):
        (self.home / "config.json").write_text(json.dumps(extra), encoding="utf-8")

    def test_add_lands_in_the_list(self):
        env = os.environ.copy()
        env["TODAY_BOARD_HOME"] = str(self.home)
        env["PYTHONPATH"] = str(ROOT)
        added = subprocess.run(
            [sys.executable, "-m", "today_board", "add", "给客户回邮件", "--source", "cli"],
            cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        item_id = added.stdout.strip()
        listed = subprocess.run(
            [sys.executable, "-m", "today_board", "list", "--json"],
            cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        items = json.loads(listed.stdout)
        match = next(i for i in items if i["id"] == item_id)
        self.assertEqual(match["status"], "pending")
        self.assertEqual(match["text"], "给客户回邮件")
        self.assertFalse(match["local"])
        self.assertIn(item_id, (self.home / "todo.md").read_text(encoding="utf-8"))

    def test_merge_writes_the_shared_list_once(self):
        self.write_config(mode="sync", merge_here=True, todo_file="sync/todo/todo.md",
                          events_file="sync/board/mini.jsonl", applied_file="sync/todo/applied.json")
        store.record({"type": "add", "id": "261112-m01", "text": "主机上的事项", "source": "cli", "status": "待确认"})
        self.assertEqual(store.merge(), 0)  # already merged when it was recorded
        text = store.path("todo_file").read_text(encoding="utf-8")
        self.assertEqual(text.count("261112-m01"), 1)
        self.assertIn("主机上的事项", text)

    def test_pending_sync_clears_after_the_host_merges(self):
        self.write_config(mode="sync", merge_here=False, todo_file="sync/todo/todo.md",
                          events_file="sync/board/macbook.jsonl", applied_file="sync/todo/applied.json",
                          id_letter={"b": "c", "m": "n"})
        event = store.record({"type": "add", "id": store.new_id("b"), "text": "从机先记一笔", "source": "manual", "status": "进行中"})
        shown = next(i for i in store.load() if i["id"] == event["id"])
        self.assertTrue(shown["local"])
        self.assertFalse(store.path("todo_file").exists())

        self.assertEqual(store.merge(), 1)  # the host applies every machine's events
        shown = next(i for i in store.load() if i["id"] == event["id"])
        self.assertFalse(shown["local"])
        self.assertIn("从机先记一笔", store.path("todo_file").read_text(encoding="utf-8"))

        store.record({"type": "status", "id": event["id"], "status": "已完成"})
        shown = next(i for i in store.load() if i["id"] == event["id"])
        self.assertEqual(shown["status"], "已完成")
        self.assertTrue(shown["local"])
        store.merge()
        shown = next(i for i in store.load() if i["id"] == event["id"])
        self.assertEqual(shown["status"], "已完成")
        self.assertFalse(shown["local"])


if __name__ == "__main__":
    unittest.main()
