"""Command line for Today Board:  today <command>"""
import argparse, json, os, pathlib, plistlib, subprocess, sys, time, urllib.request
from . import store

LABEL = "io.today-board.server"
PLIST = pathlib.Path("~/Library/LaunchAgents").expanduser() / f"{LABEL}.plist"
ZH2EN = dict(zip(store.ZH, store.EN))


def url():
    return f"http://127.0.0.1:{store.config()['port']}/"


def cmd_serve(a):
    from . import server
    server.serve()


def cmd_add(a):
    if a.time and not store.valid_time(a.time):
        sys.exit("time must look like 2026-11-13, 2026-11-13 10:00 or 2026-11-13 10:00-11:00")
    e = store.record({"type": "add", "id": store.new_id(a.origin), "text": a.text, "source": a.source,
                      "status": a.status, "time": a.time or "", "note": a.note or ""})
    print(e["id"])


def cmd_list(a):
    items = store.load()
    if a.status:
        items = [i for i in items if ZH2EN[i["status"]] == a.status]
    if a.json:
        return print(json.dumps([dict(i, status=ZH2EN[i["status"]]) for i in items], ensure_ascii=False, indent=1))
    for i in items:
        print(f"{ZH2EN[i['status']]:8} {i['id']}  {i['text']}" + (f"  [{i['time']}]" if i["time"] else ""))


def cmd_set(a):
    if not any(i["id"] == a.id for i in store.load()):
        sys.exit(f"no item {a.id}")
    store.record({"type": "status", "id": a.id, "status": a.status})


def cmd_merge(a):
    n = store.merge()
    if n or a.verbose:
        print(f"merged {n} event(s)")


def cmd_install(a):
    root = pathlib.Path(__file__).resolve().parent.parent
    store.HOME.mkdir(parents=True, exist_ok=True)
    if not (store.HOME / "config.json").exists():
        (store.HOME / "config.json").write_text(json.dumps({"mode": "local", "port": store.DEFAULTS["port"], "agent_command": "claude", "agent_cwd": "~"}, indent=2) + "\n")
    if not store.path("todo_file").exists():
        store.write_todo(["# Todo", ""], [])
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    with PLIST.open("wb") as f:
        plistlib.dump({"Label": LABEL, "ProgramArguments": [sys.executable, "-m", "today_board", "serve"], "WorkingDirectory": str(root),
                       "EnvironmentVariables": {"TODAY_BOARD_HOME": str(store.HOME), "PYTHONPATH": str(root),
                                                "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(pathlib.Path.home())},
                       "RunAtLoad": True, "KeepAlive": True,
                       "StandardOutPath": str(store.HOME / "server.log"), "StandardErrorPath": str(store.HOME / "server.log")}, f)
    uid = str(os.getuid())
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("launchctl failed: " + r.stderr.strip())
    for _ in range(20):
        try:
            urllib.request.urlopen(url() + "api/items", timeout=1)
            break
        except OSError:
            time.sleep(0.3)
    else:
        sys.exit(f"service was loaded but {url()} did not answer; see {store.HOME / 'server.log'}")
    print(f"Today Board is running at {url()}\n  data: {store.HOME}\n  next: today dock")


def cmd_uninstall(a):
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    PLIST.unlink(missing_ok=True)
    print(f"service removed. Your data is still in {store.HOME}")


def cmd_dock(a):
    c = store.config()["cmux"]
    env = dict(os.environ, CMUX_QUIET="1")
    tree = subprocess.run([c, "tree"], capture_output=True, text=True, env=env)
    if tree.returncode != 0:
        sys.exit("cmux is not running (or its CLI is not at the configured path). Open cmux first.")
    if url().rstrip("/") in tree.stdout and "dock:" in tree.stdout:
        print("already in the Dock")
    else:
        r = subprocess.run([c, "new-pane", "--type", "browser", "--placement", "dock", "--url", url(), "--focus", "false"],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            sys.exit("could not add a Dock pane: " + (r.stderr or r.stdout).strip() + "\nYour cmux may be too old to have the Dock.")
    subprocess.run([c, "right-sidebar", "set", "dock", "--no-focus"], capture_output=True, env=env)
    print("Today Board is in the cmux Dock (right sidebar).")


def main(argv=None):
    p = argparse.ArgumentParser(prog="today", description="A todo list that lives in the cmux Dock.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the local web server in the foreground").set_defaults(f=cmd_serve)
    s = sub.add_parser("add", help="add an item (for scripts, cron jobs and agents)")
    s.add_argument("text")
    s.add_argument("--status", choices=["pending", "todo"], default="pending", help="pending = waits for you to confirm (default)")
    s.add_argument("--source", default="cli", help="where it came from, shown on the board")
    s.add_argument("--time", help='fixed time, e.g. "2026-11-13 10:00-11:00"')
    s.add_argument("--note")
    s.add_argument("--origin", default="m", help="one letter used in the id (default m = machine)")
    s.set_defaults(f=cmd_add)
    s = sub.add_parser("list", help="print items")
    s.add_argument("--status", choices=store.EN)
    s.add_argument("--json", action="store_true")
    s.set_defaults(f=cmd_list)
    s = sub.add_parser("set", help="change an item's status")
    s.add_argument("id")
    s.add_argument("status", choices=store.EN)
    s.set_defaults(f=cmd_set)
    s = sub.add_parser("merge", help="sync mode: apply recorded events to the Markdown file")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(f=cmd_merge)
    sub.add_parser("install", help="run as a background service (macOS launchd)").set_defaults(f=cmd_install)
    sub.add_parser("uninstall", help="stop and remove the background service").set_defaults(f=cmd_uninstall)
    sub.add_parser("dock", help="show the board in the cmux Dock").set_defaults(f=cmd_dock)
    a = p.parse_args(argv)
    a.f(a)
