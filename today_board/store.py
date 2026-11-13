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


_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
             "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}
_PERIOD_HOUR = {"凌晨": 5, "早上": 9, "早晨": 9, "上午": 9, "中午": 12,
                "下午": 14, "晚上": 19, "晚间": 19, "夜里": 21}
_PERIODS = "凌晨|早上|早晨|上午|中午|下午|晚上|晚间|夜里"


def _num(s):
    """Read a small Arabic or Chinese number: 3, 十, 十一, 二十三."""
    s = str(s)
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        a, b = s.split("十", 1)
        return _CN_DIGITS.get(a, 1) * 10 + (_CN_DIGITS.get(b, 0) if b else 0)
    return _CN_DIGITS.get(s, 0)


def _mins(s):
    if not s:
        return 0
    if s.startswith("半"):
        return 30
    return int(re.sub(r"\D", "", s) or 0)


def _clock(hour, minute, period):
    h = _num(hour)
    if period in ("下午", "晚上", "晚间", "夜里") and h < 12:
        h += 12
    elif period == "中午" and h < 11:
        h += 12
    elif period == "凌晨" and h == 12:
        h = 0
    return f"{h % 24:02d}:{int(minute):02d}"


def parse_when(text, now=None):
    """Read a day and a time out of free text, in the form the file stores.

    "今天下午过一下订单"     -> "2026-11-13 14:00"
    "周六 10:00 开会"       -> "2026-11-14 10:00"
    "明天"                   -> "2026-11-14"
    Returns "" when the text carries no date and no time.
    """
    s = str(text).replace("今晚", "今天晚上").replace("明晚", "明天晚上")
    s = s.replace("今早", "今天早上").replace("明早", "明天早上")
    now = now or datetime.datetime.now()
    today = now.date()
    day = None

    m = re.search(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})[日号]?", s)
    if m:
        try:
            day = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            day = None
    if day is None:
        m = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})[日号]", s)
        if m:
            try:
                day = datetime.date(today.year, int(m.group(1)), int(m.group(2)))
            except ValueError:
                day = None
            if day and day < today - datetime.timedelta(days=180):
                try:
                    day = day.replace(year=today.year + 1)
                except ValueError:
                    pass
    if day is None:
        if "大后天" in s:
            day = today + datetime.timedelta(days=3)
        elif "后天" in s:
            day = today + datetime.timedelta(days=2)
        elif any(w in s for w in ("明天", "明日", "明儿", "明晨")):
            day = today + datetime.timedelta(days=1)
        elif any(w in s for w in ("今天", "今日", "今儿", "今晨")):
            day = today
    if day is None:
        m = re.search(r"(下下|下个?|这|本)?\s*(?:周|星期|礼拜)\s*([一二三四五六日天1-7])", s)
        if m:
            delta = (_WEEKDAYS[m.group(2)] - today.weekday()) % 7
            if m.group(1) in ("下", "下个"):
                delta += 7
            elif m.group(1) == "下下":
                delta += 14
            elif m.group(1) in ("这", "本"):
                delta = _WEEKDAYS[m.group(2)] - today.weekday()
            day = today + datetime.timedelta(days=delta)

    def period_before(pos):
        found = re.search(rf"({_PERIODS})\s*$", s[:pos])
        return found.group(1) if found else None

    clock = ""
    m = re.search(r"(?<!\d)(\d{1,2})[:：](\d{2})\s*[-–—~至到]\s*(\d{1,2})[:：](\d{2})", s)
    if m:
        p = period_before(m.start())
        clock = _clock(m.group(1), m.group(2), p) + "–" + _clock(m.group(3), m.group(4), p)
    else:
        m = re.search(r"(?<!\d)(\d{1,2})[:：](\d{2})(?!\d)", s)
        if m:
            clock = _clock(m.group(1), m.group(2), period_before(m.start()))
    if not clock:
        m = re.search(rf"({_PERIODS})?\s*(\d{{1,2}}|[一二两三四五六七八九十]{{1,3}})\s*点\s*(半|\d{{1,2}}分?)?"
                      rf"\s*(?:[-–—~]|到|至)\s*({_PERIODS})?\s*(\d{{1,2}}|[一二两三四五六七八九十]{{1,3}})\s*点\s*(半|\d{{1,2}}分?)?", s)
        if m:
            p1 = m.group(1) or period_before(m.start())
            p2 = m.group(4) or p1
            clock = _clock(m.group(2), _mins(m.group(3)), p1) + "–" + _clock(m.group(5), _mins(m.group(6)), p2)
    if not clock:
        m = re.search(rf"({_PERIODS})?\s*(\d{{1,2}}|[一二两三四五六七八九十]{{1,3}})\s*点\s*(半|\d{{1,2}}分?)?", s)
        if m:
            p = m.group(1) or period_before(m.start())
            # 「一点」单说不带上午/下午/分钟，多半是「差一点」，不当成时间
            if p or m.group(3) or str(m.group(2)) != "一":
                clock = _clock(m.group(2), _mins(m.group(3)), p)
    if not clock:
        m = re.search(rf"({_PERIODS})", s)
        if m:
            clock = f"{_PERIOD_HOUR[m.group(1)]:02d}:00"

    if day is None and not clock:
        return ""
    day = day or today
    return f"{day.isoformat()} {clock}" if clock else day.isoformat()


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
    if (event.get("type") == "add" and not str(event.get("time", "")).strip()
            and str(event.get("source", "manual")) in ("manual", "cli")):
        event["time"] = parse_when(event.get("text", ""))
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
