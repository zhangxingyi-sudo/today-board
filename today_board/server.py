"""Local web server for Today Board. Binds to 127.0.0.1 only."""
import json, os, pathlib, re, shlex, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import store

PAGE = pathlib.Path(__file__).with_name("page.html")


def cmux(*args, timeout=15):
    return subprocess.run([store.config()["cmux"], *args], capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, CMUX_QUIET="1"))


def handle(item):
    """Open a cmux workspace for this item with an agent already briefed on it; reuse it if it is still open."""
    c = store.config()
    data = store.HOME / "data"
    data.mkdir(parents=True, exist_ok=True)
    mp = data / "workspaces.json"
    try:
        m = json.loads(mp.read_text())
    except (OSError, ValueError):
        m = {}
    ref = m.get(item["id"])
    if ref and ref in cmux("workspace", "list").stdout:
        cmux("workspace", "select", ref)
        return {"ok": True, "workspace": ref, "reused": True}
    prompt = (f"请帮我处理这件待办。\n\n编号：{item['id']}\n内容：{item['text']}\n来源：{item['source']}（{item['date']}）"
              + (f"\n时间：{item['time']}" if item.get("time") else "") + (f"\n备注：{item['note']}" if item.get("note") else "")
              + "\n\n先用两三句话说明你对这件事的理解和打算怎么做，需要我补充什么就问我，等我确认后再动手。")
    pf = data / "prompts" / f"{item['id']}.txt"
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(prompt)
    r = cmux("workspace", "create", "--name", re.sub(r"\s+", " ", item["text"])[:18], "--description", item["id"],
             "--cwd", str(pathlib.Path(c["agent_cwd"]).expanduser()),
             "--command", f'{c["agent_command"]} "$(cat {shlex.quote(str(pf))})"', "--focus", "true")
    g = re.search(r"workspace:\d+", r.stdout + r.stderr)
    if r.returncode != 0 or not g:
        return {"ok": False, "error": (r.stderr or r.stdout).strip()[-300:] or "cmux did not respond"}
    m[item["id"]] = g.group(0)
    mp.write_text(json.dumps(m))
    return {"ok": True, "workspace": g.group(0), "reused": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/items":
            self._send(200, json.dumps(store.load(), ensure_ascii=False))
        elif self.path in ("/", "/sidebar"):
            self._send(200, PAGE.read_text(), "text/html")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        # Only same-machine pages may write: check both the Host header and, when present, the Origin.
        host = self.headers.get("Host", "").split(":")[0]
        origin = self.headers.get("Origin", "")
        if host not in ("127.0.0.1", "localhost") or (origin and not re.match(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$", origin)):
            return self._send(403, "forbidden", "text/plain")
        try:
            e = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            return self._send(400, "bad request", "text/plain")
        if self.path == "/api/handle":
            it = next((i for i in store.load() if i["id"] == e.get("id")), None)
            if not it:
                return self._send(404, json.dumps({"ok": False, "error": "item not found"}))
            try:
                return self._send(200, json.dumps(handle(it), ensure_ascii=False))
            except Exception as x:  # the page shows the message; never crash the server on a cmux hiccup
                return self._send(200, json.dumps({"ok": False, "error": str(x)[:300]}, ensure_ascii=False))
        if self.path != "/api/event":
            return self._send(404, "not found", "text/plain")
        try:
            t = e.get("type", "status")
            rec = {"type": t}
            if t == "add":
                rec.update(id=store.new_id("b"), text=store.clean(e["text"], 500), source="manual")
                assert rec["text"]
            else:
                assert re.fullmatch(store.ID, e["id"])
                rec["id"] = e["id"]
                if t == "status":
                    assert e["status"] in store.ZH
                    rec["status"] = e["status"]
                elif t == "edit":
                    rec["text"] = store.clean(e["text"], 500)
                    assert rec["text"]
                elif t == "note":
                    rec["note"] = str(e["note"]).strip()[:2000]
                elif t == "time":
                    rec["time"] = str(e["time"]).strip()
                    assert store.valid_time(rec["time"])
                else:
                    raise ValueError(t)
        except (AssertionError, KeyError, ValueError, TypeError):
            return self._send(400, "bad request", "text/plain")
        self._send(200, json.dumps(store.record(rec), ensure_ascii=False))


def serve():
    port = int(store.config()["port"])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
