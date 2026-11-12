"""Todo list storage for Today Board.

The list is one plain Markdown file, so people, scripts and coding agents can all read and write it:

    - [待确认] 261112-m01 | Review the Q4 plan | daily-summary | 2026-11-12
      - 时间：2026-11-13 10:00–11:00
      - 备注：waiting on numbers from finance

Everything done on the board is first appended to an event log (one JSON object per line).
Events are then merged into the Markdown file. In `local` mode that happens right away;
in `sync` mode every machine appends to its own event file and exactly one machine (`merge_here`)
merges them all, so a list shared through git never has two writers for the same file.
"""
import datetime, hashlib, json, os, pathlib, re

HOME = pathlib.Path(os.environ.get("TODAY_BOARD_HOME", "~/.today-board")).expanduser()
DEFAULTS = {
    "mode": "local",                 # local: one machine. sync: several machines share the list through a git repo.
    "merge_here": False,             # sync mode only: true on the one machine that writes todo_file
    "todo_file": "todo.md",          # relative paths are resolved against HOME
    "events_file": "events.jsonl",
    "applied_file": "applied.json",
    "port": 8787,
    "agent_command": "claude",       # what "处理 ▸" starts in a new cmux workspace
    "agent_cwd": "~",
    "cmux": "/Applications/cmux.app/Contents/Resources/bin/cmux",
    "status_style": "zh",            # how statuses are written to the file: zh or en
}
ZH = ("待确认", "进行中", "已完成", "已推迟", "已取消")
EN = ("pending", "todo", "done", "later", "ignored")
TO_ZH = {**{z: z for z in ZH}, **dict(zip(EN, ZH))}
ID = r"\d{6}-[a-z]\d{2,}"
LINE = re.compile(rf"^- \[(?P<status>[^\]]+)\]\s*(?P<id>{ID})\s*\|\s*(?P<text>.*?)\s*\|\s*(?P<source>[^|]*?)\s*\|\s*(?P<date>\d{{4}}-\d{{2}}-\d{{2}})\s*$")
SUB = re.compile(r"^\s+- (?P<k>时间|备注|time|note)[:：]\s*(?P<v>.*)$", re.I)
TIME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2})(?:\s*[–—\-~]\s*(\d{1,2}:\d{2}))?)?$")


def config():
    c = dict(DEFAULTS)
    try:
        c.update(json.loads((HOME / "config.json").read_text()))
    except (OSError, ValueError):
        pass
    return c


def path(key):
    p = pathlib.Path(str(config()[key])).expanduser()
    return p if p.is_absolute() else HOME / p


def parse(text):
    pre, items, cur = [], [], None
    for l in text.splitlines():
        m = LINE.match(l)
        if m:
            cur = dict(m.groupdict(), note="", time="")
            cur["status"] = TO_ZH.get(cur["status"].strip().lower(), TO_ZH.get(cur["status"].strip(), "待确认"))
            items.append(cur)
            continue
        s = SUB.match(l)
        if s and cur is not None:
            if s.group("k").lower() in ("时间", "time"):
                cur["time"] = s.group("v").strip()
            else:
                cur["note"] = (cur["note"] + "\n" + s.group("v")).strip()
            continue
        if cur is None:
            pre.append(l)
        elif l.strip():
            cur["note"] = (cur["note"] + "\n" + l.strip()).strip()  # keep stray text instead of dropping it
    return pre, items


def render(pre, items):
    en = config()["status_style"] == "en"
    st = dict(zip(ZH, EN)) if en else {z: z for z in ZH}
    kt, kn = ("time", "note") if en else ("时间", "备注")
    sep = ": " if en else "："
    out = list(pre) or ["# Todo", ""]
    while out and not out[-1].strip():
        out.pop()
    out.append("")
    for i in items:
        out.append(f"- [{st[i['status']]}] {i['id']} | {i['text']} | {i['source']} | {i['date']}")
        if i.get("time"):
            out.append(f"  - {kt}{sep}{i['time']}")
        for n in (i.get("note") or "").splitlines():
            if n.strip():
                out.append(f"  - {kn}{sep}{n.strip()}")
    return "\n".join(out) + "\n"


def read_todo():
    p = path("todo_file")
    return parse(p.read_text(errors="replace")) if p.exists() else (["# Todo", ""], [])


def write_todo(pre, items):
    p = path("todo_file")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(render(pre, items))
    tmp.replace(p)


def _key(line):
    return hashlib.sha1(line.encode()).hexdigest()[:16]


def applied_set():
    try:
        return set(json.loads(path("applied_file").read_text()))
    except (OSError, ValueError):
        return set()


def _read_events(p):
    out = []
    if p.exists():
        for l in p.read_text().splitlines():
            l = l.strip()
            if l:
                try:
                    out.append((_key(l), json.loads(l)))
                except ValueError:
                    pass
    return out


def all_events(everyone=False):
    """Events recorded on this machine; with everyone=True, events from every machine's file in the same folder."""
    own = path("events_file")
    files = sorted(own.parent.glob("*.jsonl")) if everyone and own.parent.exists() else [own]
    return [e for f in files for e in _read_events(f)]


def merges_here():
    c = config()
    return c["mode"] == "local" or bool(c.get("merge_here"))


def pending_events(everyone=False):
    done = applied_set()
    return sorted((x for x in all_events(everyone) if x[0] not in done), key=lambda x: x[1].get("at", ""))


def clean(s, limit):
    return re.sub(r"\s+", " ", str(s)).replace("|", "｜").strip()[:limit]


def apply(items, events):
    """Apply events to items in place. Returns how many took effect."""
    by, n = {i["id"]: i for i in items}, 0
    for _, e in events:
        t = e.get("type", "status")
        if t == "add":
            if e.get("id") and e["id"] not in by:
                it = {"id": e["id"], "status": TO_ZH.get(e.get("status", "进行中"), "进行中"), "text": clean(e.get("text", ""), 500),
                      "source": clean(e.get("source", "manual"), 60) or "manual", "date": e.get("at", "")[:10] or datetime.date.today().isoformat(),
                      "note": str(e.get("note", "")).strip(), "time": e.get("time", "") if valid_time(e.get("time", "")) else ""}
                items.append(it); by[it["id"]] = it; it["touched"] = True; n += 1
            continue
        it = by.get(e.get("id"))
        if not it:
            continue
        if t == "status" and e.get("status") in TO_ZH:
            it["status"] = TO_ZH[e["status"]]; it["changed"] = e.get("at", "")
        elif t == "edit" and clean(e.get("text", ""), 500):
            it["text"] = clean(e["text"], 500)
        elif t == "note":
            it["note"] = str(e.get("note", "")).strip()[:2000]
        elif t == "time" and valid_time(e.get("time", "")):
            it["time"] = e["time"].strip()
        else:
            continue
        it["touched"] = True; n += 1
    return n


def merge():
    """Write pending events from every machine into the Markdown file and remember them as applied."""
    ev = pending_events(everyone=True)
    if not ev:
        return 0
    pre, items = read_todo()
    n = apply(items, ev)
    for i in items:
        i.pop("touched", None); i.pop("changed", None)
    write_todo(pre, items)
    a = path("applied_file")
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_text(json.dumps(sorted(applied_set() | {k for k, _ in ev})))
    return n


def record(event):
    """Append one event. On the machine that owns the Markdown file, merge immediately so it is always current."""
    event = dict(event, at=datetime.datetime.now().isoformat(timespec="seconds"))
    p = path("events_file")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    if merges_here():
        merge()
    return event


def new_id(origin="b"):
    """Unique id: yymmdd + origin letter + running number. b = added on the board, m = added by automation.
    In sync mode give each machine its own letters (config "id_letter") so two machines never mint the same id."""
    origin = config().get("id_letter", {}).get(origin, origin) if isinstance(config().get("id_letter"), dict) else origin
    day = datetime.date.today().strftime("%y%m%d")
    used = {i["id"] for i in read_todo()[1]} | {e.get("id") for _, e in all_events(everyone=True)}
    n = 1
    while f"{day}-{origin}{n:02d}" in used:
        n += 1
    return f"{day}-{origin}{n:02d}"


def valid_time(s):
    return s == "" or bool(TIME.match(str(s).strip()))


def load():
    """Items as the board should show them: the file plus events not merged yet."""
    _, items = read_todo()
    apply(items, pending_events())
    for i in items:
        i["local"] = bool(i.pop("touched", False))
    return items
