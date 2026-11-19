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

    def test_project_stays_out_of_the_note(self):
        self.write_config(mode="local", projects=["work", "home"])
        store.record({"type": "add", "id": "261112-m01", "text": "准备评审材料", "source": "cli",
                      "status": "待确认", "project": "work"})
        text = store.path("todo_file").read_text(encoding="utf-8")
        self.assertIn("项目：work、home", text)
        self.assertIn("项目：work", text)
        item = next(i for i in store.load() if i["id"] == "261112-m01")
        self.assertEqual(item["project"], "work")
        self.assertEqual(item["note"], "")
        store.record({"type": "project", "id": "261112-m01", "project": "home"})
        item = next(i for i in store.load() if i["id"] == "261112-m01")
        self.assertEqual(item["project"], "home")

    def test_project_lifecycle_and_multi_machine_sync(self):
        # Secondary machine has no local projects configured; host has one legacy project.
        self.write_config(mode="sync", merge_here=False, todo_file="sync/todo/todo.md",
                          events_file="sync/board/macbook.jsonl", applied_file="sync/todo/applied.json",
                          id_letter={"b": "c", "m": "n"})
        store.record({"type": "project_add", "name": "Alpha"})
        e_add = store.record({"type": "add", "id": store.new_id("b"), "text": "搭建原型", "source": "manual",
                              "status": "进行中", "project": "Beta"})
        # Immediately visible locally on secondary machine before merge
        self.assertEqual(list(store.projects()), ["Alpha", "Beta"])
        self.assertEqual(next(i for i in store.load() if i["id"] == e_add["id"])["project"], "Beta")

        # Host merges secondary machine's events into todo.md
        self.write_config(mode="sync", merge_here=True, todo_file="sync/todo/todo.md",
                          events_file="sync/board/mini.jsonl", applied_file="sync/todo/applied.json",
                          projects=["Legacy"])
        self.assertGreaterEqual(store.merge(), 2)
        md = store.path("todo_file").read_text(encoding="utf-8")
        self.assertIn("项目：Legacy、Alpha、Beta", md)
        self.assertEqual(list(store.projects()), ["Legacy", "Alpha", "Beta"])

        # Rename Beta -> Gamma on host updates header and item
        store.record({"type": "project_rename", "old": "Beta", "new": "Gamma"})
        self.assertEqual(list(store.projects()), ["Legacy", "Alpha", "Gamma"])
        self.assertEqual(next(i for i in store.load() if i["id"] == e_add["id"])["project"], "Gamma")

        # Delete every project; legacy config must not resurrect deleted projects
        for name in ("Legacy", "Alpha", "Gamma"):
            store.record({"type": "project_delete", "name": name})
        self.assertEqual(list(store.projects()), [])
        self.assertEqual(next(i for i in store.load() if i["id"] == e_add["id"])["project"], "")

    def test_ensure_project_header_migrates_once(self):
        self.write_config(mode="sync", merge_here=True, todo_file="sync/todo/todo.md",
                          events_file="sync/board/mini.jsonl", applied_file="sync/todo/applied.json",
                          projects=["ProjA", "ProjB"])
        store.write_todo(["# Todo", ""], [])
        self.assertTrue(store.ensure_project_header())
        self.assertIn("项目：ProjA、ProjB", store.path("todo_file").read_text(encoding="utf-8"))
        self.assertFalse(store.ensure_project_header())

    def test_cli_projects_and_add_new_project(self):
        env = os.environ.copy()
        env["TODAY_BOARD_HOME"] = str(self.home)
        env["PYTHONPATH"] = str(ROOT)
        subprocess.run([sys.executable, "-m", "today_board", "add", "写设计稿", "--project", "Design"],
                       cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        subprocess.run([sys.executable, "-m", "today_board", "projects", "--add", "Ops"],
                       cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        out = subprocess.run([sys.executable, "-m", "today_board", "projects", "--json"],
                             cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout), ["Design", "Ops"])
        subprocess.run([sys.executable, "-m", "today_board", "projects", "--rename", "Design", "UX"],
                       cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        out = subprocess.run([sys.executable, "-m", "today_board", "projects", "--json"],
                             cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout), ["UX", "Ops"])
        subprocess.run([sys.executable, "-m", "today_board", "projects", "--delete", "Ops"],
                       cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        out = subprocess.run([sys.executable, "-m", "today_board", "projects", "--json"],
                             cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout), ["UX"])

    def test_http_api_project_events(self):
        import threading, urllib.request
        from http.server import ThreadingHTTPServer
        from today_board import server

        self.write_config(mode="local")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            def api(path, body=None):
                data = None if body is None else json.dumps(body).encode()
                req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                             headers={"Content-Type": "application/json"} if data else {})
                with urllib.request.urlopen(req, timeout=3) as r:
                    return json.loads(r.read().decode())

            api("/api/event", {"type": "project_add", "name": "Roadmap"})
            added = api("/api/event", {"type": "add", "text": "整理需求", "project": "Hardware"})
            self.assertEqual(api("/api/projects"), ["Roadmap", "Hardware"])
            api("/api/event", {"type": "project_rename", "old": "Hardware", "new": "Devices"})
            self.assertEqual(api("/api/projects"), ["Roadmap", "Devices"])
            items = api("/api/items")
            self.assertEqual(next(i for i in items if i["id"] == added["id"])["project"], "Devices")
            api("/api/event", {"type": "project_delete", "name": "Devices"})
            self.assertEqual(api("/api/projects"), ["Roadmap"])
            items = api("/api/items")
            self.assertEqual(next(i for i in items if i["id"] == added["id"])["project"], "")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
