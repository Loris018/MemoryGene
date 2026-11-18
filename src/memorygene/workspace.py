"""Indexed, versioned task cards for an explicitly bound local project."""

import json
import re

TEXT = {"type": "string"}
INT = {"type": "integer", "minimum": 0}
KINDS = ("goal", "requirement", "step", "decision", "preference")
STATES = ("active", "planned", "in_progress", "done", "cancelled")
MODES = {
    "coding": "State the relevant assumptions, follow the project's constraints, and verify the change.",
    "study": "Explain the source material first. Label any additional examples or background separately.",
    "general": "Follow the current goal and constraints. Check the next unfinished step.",
}
TASK_SPEC = {
    "task_remove": (
        "Only on the user’s explicit request: erase this entry and its quoted history from the bound project. Read its current version first. Keep a content-free revision marker against stale writes.",
        {"task": TEXT, "item": TEXT, "expected_version": INT},
        ["task", "item", "expected_version"],
    ),
    "task_propose": (
        "Keep a conflicting or uncertain option separately for review. List outstanding options by omitting value and quote. An option never changes a current entry.",
        {"task": TEXT, "item": TEXT, "value": TEXT, "quote": TEXT},
        ["task", "item"],
    ),
    "task_check": (
        "Compare the item versions carried in context to current task state and return omitted, stale or dependent entries. Follow next_cursor until complete.",
        {
            "task": TEXT,
            "seen": {"type": "object", "additionalProperties": INT},
            "remembered": {"type": "object", "additionalProperties": TEXT},
            "after": TEXT,
        },
        ["task", "seen"],
    ),
    "task_related": (
        "Follow the dependencies of a task entry and list upstream changes.",
        {"task": TEXT, "item": TEXT},
        ["task", "item"],
    ),
    "task_resume": (
        "Find a task from natural language. Return its current goal, requirements, progress, next work and working style. Ask if ambiguous. Use task and after to page through all entries.",
        {"query": TEXT, "task": TEXT, "after": TEXT},
        [],
    ),
    "task_record": (
        "Version one task-card entry. Save a goal with a descriptive title to register a task. Distinguish planned, in_progress, done and cancelled. Supply the actual evidence, its speaker and the version read. User claims and assistant reports are attributed, not verified. Link dependent items in the same task by key.",
        {
            "task": TEXT,
            "item": TEXT,
            "kind": {"enum": list(KINDS)},
            "state": {"enum": list(STATES)},
            "mode": {"enum": ["auto", *MODES]},
            "value": TEXT,
            "quote": TEXT,
            "speaker": {"enum": ["user", "assistant"]},
            "certainty": {"enum": ["explicit", "uncertain", "inferred"]},
            "expected_version": INT,
            "depends_on": {"type": "array", "items": TEXT, "maxItems": 12},
            "proposal": INT,
            "clip": TEXT,
        },
        [
            "task",
            "item",
            "kind",
            "state",
            "value",
            "quote",
            "speaker",
            "certainty",
            "expected_version",
        ],
    ),
    "task_search": (
        "Find matching current entries in one task. Results include keys for retrieving full history.",
        {"task": TEXT, "query": TEXT},
        ["task", "query"],
    ),
    "task_clip": (
        "List this client’s temporary windows for the task, or review/discard one by its opaque ID. To confirm, use task_record with clip and a matching user quote.",
        {"task": TEXT, "clip": TEXT, "action": {"enum": ["list", "read", "discard"]}},
        ["task", "action"],
    ),
}
MIGRATIONS = (
    "CREATE TABLE IF NOT EXISTS card_meta(task TEXT,item TEXT,version INTEGER,kind TEXT,state TEXT,mode TEXT,speaker TEXT,links TEXT,PRIMARY KEY(task,item,version))",
    "CREATE TABLE IF NOT EXISTS card_terms(term TEXT,task TEXT,item TEXT,weight INTEGER NOT NULL,PRIMARY KEY(term,task,item))",
    "CREATE INDEX IF NOT EXISTS card_terms_by_item ON card_terms(task,item)",
    "CREATE TABLE IF NOT EXISTS capture_stream(client TEXT,session TEXT,task TEXT,expiry INTEGER,recent TEXT,last_id TEXT,PRIMARY KEY(client,session))",
    "CREATE INDEX IF NOT EXISTS capture_expiry ON capture_stream(expiry)",
    "CREATE TABLE IF NOT EXISTS capture_clip(id TEXT PRIMARY KEY,task TEXT,client TEXT,session TEXT,expiry INTEGER,samples TEXT)",
    "CREATE INDEX IF NOT EXISTS clip_by_session ON capture_clip(client,session)",
    "CREATE INDEX IF NOT EXISTS clip_expiry ON capture_clip(expiry)",
)
STOP = set(
    "the and for from this that task continue resume work next please with what done just use project yesterday current".split()
)
KEY = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


def tokens(text):
    found = set()
    for run in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", text.lower()):
        if run.isascii():
            if run not in STOP:
                found.add(run)
        else:
            found.update(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return sorted(
        found - {"继续", "接手", "昨天", "那个", "任务", "一下", "我们", "目前"}
    )


def index(db, task, item, value, kind):
    weights = {s: 3 if kind == "goal" else 1 for s in tokens(value)}
    weights.update({s: 4 for s in tokens(item)})
    weights.update({s: 8 for s in tokens(task)})
    db.execute("DELETE FROM card_terms WHERE task=? AND item=?", (task, item))
    db.executemany(
        "INSERT INTO card_terms VALUES(?,?,?,?)",
        ((w, task, item, k) for w, k in weights.items()),
    )


def migrate(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == 6:
        return
    if version > 6:
        raise ValueError("newer project database requires an updated MemoryGene")
    with db:
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            for sql in MIGRATIONS:
                db.execute(sql)
            for row in db.execute(
                "SELECT task,item,value FROM heads JOIN versions USING(task,item,version)"
            ):
                index(db, *row, "decision")
        if version < 2:
            db.execute(
                "CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY,task TEXT,item TEXT,client TEXT,value TEXT,quote TEXT,base INTEGER,resolution INTEGER,UNIQUE(task,item,client,value,quote,base))"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS proposals_item ON proposals(task,item,resolution)"
            )
        if version < 3:
            db.execute(
                "CREATE TABLE IF NOT EXISTS session_task(client TEXT,session TEXT,task TEXT,expiry INTEGER,PRIMARY KEY(client,session))"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS session_task_expiry ON session_task(expiry)"
            )
        if version < 4:
            if not any(
                row[1] == "following"
                for row in db.execute("PRAGMA table_info(capture_clip)")
            ):
                db.execute(
                    "ALTER TABLE capture_clip ADD COLUMN following INTEGER NOT NULL DEFAULT 1"
                )
        if version < 5:
            db.execute(
                "CREATE TABLE IF NOT EXISTS closed_tasks(task TEXT PRIMARY KEY,state TEXT NOT NULL)"
            )
            db.execute(
                "INSERT OR REPLACE INTO closed_tasks SELECT h.task,m.state FROM heads h JOIN card_meta m USING(task,item,version) WHERE m.kind='goal' AND m.state IN ('done','cancelled')"
            )
        if version < 6:
            db.execute(
                "CREATE TABLE IF NOT EXISTS removed(task TEXT,item TEXT,version INTEGER,PRIMARY KEY(task,item))"
            )
            db.execute("PRAGMA user_version=6")


def matches(db, query, task=None):
    words = tokens(query)[:80]
    if not words:
        return []
    params = list(words)
    where = "term IN (" + ",".join("?" for _ in words) + ")"
    if task:
        where += " AND task=?"
        params.append(task)
        sql = f"SELECT item,sum(weight) FROM card_terms WHERE {where} GROUP BY item ORDER BY 2 DESC,item LIMIT 12"
    else:
        sql = f"SELECT task,sum(w) FROM (SELECT term,task,max(weight) w FROM card_terms WHERE {where} AND task!='defaults' AND task NOT IN (SELECT task FROM closed_tasks) GROUP BY term,task) GROUP BY task ORDER BY 2 DESC,task LIMIT 5"
    return db.execute(sql, params).fetchall()


def resolve(db, query):
    exact = []
    for word in set(re.findall(r"[a-z][a-z0-9_.-]{0,63}", query.lower())):
        if db.execute("SELECT 1 FROM heads WHERE task=? LIMIT 1", (word,)).fetchone():
            exact.append(word)
    if len(exact) == 1:
        return exact[0], []
    if exact:
        return None, sorted(exact)
    declared = re.search(
        r"(?:名为|任务名[叫为是]?|任务叫|task (?:called|named))\s*[`“\"]?([a-z][a-z0-9_.-]*)",
        query,
        re.I,
    )
    if declared:
        return None, []
    hits = matches(db, query)
    if hits and (len(hits) == 1 or hits[0][1] >= hits[1][1] * 1.6):
        words = tokens(query)[:80]
        marks = ",".join("?" for _ in words)
        strong = [
            r[0]
            for r in db.execute(
                f"SELECT DISTINCT term FROM card_terms WHERE task=? AND term IN ({marks})",
                (hits[0][0], *words),
            )
        ]
        if len(strong) >= 2 or any(w.isascii() and len(w) >= 4 for w in strong):
            return hits[0][0], []
    if hits:
        return None, [r[0] for r in hits]
    tasks = [
        r[0]
        for r in db.execute(
            "SELECT DISTINCT task FROM heads WHERE task!='defaults' AND task NOT IN (SELECT task FROM closed_tasks) ORDER BY task LIMIT 6"
        )
    ]
    if len(tasks) == 1 and re.search(
        r"继续|接着|接手|\b(continue|resume)\b", query, re.I
    ):
        return tasks[0], []
    return None, tasks


SELECT = """SELECT v.task,v.item,v.version,v.value,v.quote,v.client AS writer_client,
 coalesce(m.kind,'decision') kind,coalesce(m.state,'active') state,coalesce(m.speaker,'user') speaker,
 coalesce(m.mode,'auto') mode,coalesce(m.links,'{}') links
 FROM heads h JOIN versions v USING(task,item,version) LEFT JOIN card_meta m USING(task,item,version)"""


def current(db, task, item):
    row = db.execute(SELECT + " WHERE h.task=? AND h.item=?", (task, item)).fetchone()
    if not row:
        return None
    result = dict(row)
    links = json.loads(result.pop("links"))
    _, stale, limited = dependencies(db, task, item) if links else (set(), set(), False)
    result["review_required"] = bool(stale or limited)
    result["depends_on"] = list(links)
    return result


def style(text):
    if re.search(r"课件|复习|课程|学习|lecture|study|tutor", text, re.I):
        return "study"
    if re.search(
        r"代码|编程|调试|测试|coding|code|debug|software|release|deploy|python",
        text,
        re.I,
    ):
        return "coding"
    return "general"


def resume(db, args):
    task = args.get("task")
    query = args.get("query", "")
    if not isinstance(query, str) or len(query) > 4000:
        raise ValueError("invalid query")
    if not task:
        task, choices = resolve(db, query)
        if not task:
            return {"status": "choose_task" if choices else "empty", "choices": choices}
    if not isinstance(task, str) or not KEY.fullmatch(task):
        raise ValueError("invalid task")
    after = args.get("after", "")
    if not isinstance(after, str) or (after and not KEY.fullmatch(after)):
        raise ValueError("invalid cursor")
    keys = [
        r[0]
        for r in db.execute(
            "SELECT item FROM heads WHERE task=? AND item>? ORDER BY item LIMIT 9",
            (task, after),
        )
    ]
    closed = db.execute(
        "SELECT state FROM closed_tasks WHERE task=?", (task,)
    ).fetchone()
    records = [current(db, task, k) for k in keys[:8]]
    goal = db.execute(
        SELECT
        + " WHERE h.task=? AND m.kind='goal' AND m.state='active' ORDER BY h.item LIMIT 1",
        (task,),
    ).fetchone()
    preferences = {}
    for scope in dict.fromkeys(("defaults", task)):
        for pref in db.execute(
            SELECT
            + " WHERE h.task=? AND m.kind='preference' AND m.state='active' ORDER BY h.item LIMIT 17",
            (scope,),
        ):
            preferences[pref["item"]] = {
                "value": pref["value"],
                "scope": scope,
                "version": pref["version"],
            }
    focus = {}
    for label, kind, states in [
        ("requirements", "requirement", ("active", "in_progress")),
        ("next", "step", ("in_progress", "planned")),
        ("completed", "step", ("done", "done")),
    ]:
        items = db.execute(
            "SELECT m.item,h.version,v.value FROM card_meta m JOIN heads h USING(task,item,version) JOIN versions v USING(task,item,version) WHERE m.task=? AND m.kind=? AND m.state IN (?,?) ORDER BY CASE WHEN m.state='in_progress' THEN 0 ELSE 1 END,m.item LIMIT 4",
            (task, kind, *states),
        ).fetchall()
        focus[label] = {
            "items": [
                {
                    "item": row[0],
                    "version": row[1],
                    "preview": row[2][:110],
                    "shortened": len(row[2]) > 110,
                }
                for row in items[:3]
            ],
            "more": len(items) > 3,
        }
    mode = (
        goal["mode"]
        if goal and goal["mode"] != "auto"
        else style(task + " " + (goal["value"] if goal else "") + " " + query)
    )
    return {
        "status": closed[0] if closed else ("ready" if records or after else "empty"),
        "task": task,
        "mode": mode,
        "working_style": MODES[mode],
        "preferences": preferences,
        "goal": goal["value"] if goal else None,
        "entries": records,
        "focus": focus,
        "next_cursor": keys[7] if len(keys) > 8 else None,
        "check": ["missing goal"] if not goal else [],
    }


def metadata(db, args):
    kind, state = args["kind"], args["state"]
    mode = args.get("mode", "auto")
    if kind not in KINDS or state not in STATES or mode not in ("auto", *MODES):
        raise ValueError("invalid card classification")
    speaker = args["speaker"]
    if speaker not in ("user", "assistant"):
        raise ValueError("invalid speaker")
    if speaker == "assistant" and kind != "step":
        raise ValueError("user evidence required for this entry")
    previous = db.execute(
        "SELECT m.mode,m.links FROM heads h JOIN card_meta m USING(task,item,version) WHERE h.task=? AND h.item=?",
        (args["task"], args["item"]),
    ).fetchone()
    if previous:
        if "mode" not in args:
            mode = previous["mode"]
        if "depends_on" not in args:
            return kind, state, mode, speaker, previous["links"]
    deps = args.get("depends_on", [])
    if not isinstance(deps, list) or len(deps) > 12:
        raise ValueError("invalid dependencies")
    links = {}
    for item in deps:
        if not isinstance(item, str) or not KEY.fullmatch(item) or item == args["item"]:
            raise ValueError("invalid dependency")
        row = db.execute(
            "SELECT version FROM heads WHERE task=? AND item=?", (args["task"], item)
        ).fetchone()
        if not row:
            raise ValueError("unknown dependency")
        visited, _, limited = dependencies(db, args["task"], item)
        if args["item"] in visited or limited:
            raise ValueError("dependency cycle or traversal limit")
        links[item] = row[0]
    return kind, state, mode, speaker, json.dumps(links)


def dependencies(db, task, item):
    """Traverse the recorded dependency graph, comparing each saved edge revision."""
    pending = [item]
    visited = set()
    stale = set()
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        if len(visited) > 256:
            return visited, stale, True
        row = db.execute(
            "SELECT m.links FROM heads h LEFT JOIN card_meta m USING(task,item,version) WHERE h.task=? AND h.item=?",
            (task, node),
        ).fetchone()
        for dep, expected in json.loads(row[0] or "{}").items() if row else ():
            latest = db.execute(
                "SELECT version FROM heads WHERE task=? AND item=?", (task, dep)
            ).fetchone()
            if not latest or latest[0] != expected:
                stale.add(dep)
            pending.append(dep)
    return visited, stale, False


def check_page(db, args):
    seen = args["seen"]
    if (
        not isinstance(seen, dict)
        or len(seen) > 256
        or any(
            not KEY.fullmatch(k) or type(v) is not int or v < 0 for k, v in seen.items()
        )
    ):
        raise ValueError("expected up to 256 item versions")
    packet = resume(db, {"task": args["task"], "after": args.get("after", "")})
    remembered = args.get("remembered", {})
    if (
        not isinstance(remembered, dict)
        or len(remembered) > 256
        or any(not isinstance(v, str) or len(v) > 600 for v in remembered.values())
    ):
        raise ValueError("invalid remembered values")
    repairs = [
        r
        for r in packet["entries"]
        if seen.get(r["item"]) != r["version"]
        or r["review_required"]
        or (r["item"] in remembered and remembered[r["item"]] != r["value"])
    ]
    removed = [
        k
        for k in seen
        if db.execute(
            "SELECT 1 FROM removed WHERE task=? AND item=?", (args["task"], k)
        ).fetchone()
    ]
    return {
        "removed": removed,
        "status": "review" if removed or repairs or packet["check"] else "current_page",
        "entries": repairs,
        "next_cursor": packet["next_cursor"],
        "check": packet["check"],
    }


def store_revision(db, task, item, version, client, value, quote, meta):
    """Caller must already hold the write lock and have compared the head."""
    db.execute(
        "INSERT INTO versions VALUES(?,?,?,?,?,?)",
        (task, item, version, value, quote, client),
    )
    db.execute(
        "INSERT INTO heads VALUES(?,?,?) ON CONFLICT(task,item) DO UPDATE SET version=excluded.version",
        (task, item, version),
    )
    db.execute("DELETE FROM removed WHERE task=? AND item=?", (task, item))
    if meta:
        db.execute(
            "INSERT INTO card_meta VALUES(?,?,?,?,?,?,?,?)",
            (task, item, version, *meta),
        )
    if meta and meta[0] == "goal":
        if meta[1] in ("done", "cancelled"):
            db.execute(
                "INSERT OR REPLACE INTO closed_tasks VALUES(?,?)", (task, meta[1])
            )
        else:
            db.execute("DELETE FROM closed_tasks WHERE task=?", (task,))
    index(db, task, item, value, meta[0] if meta else "decision")
