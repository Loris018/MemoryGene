"""The assistant's own impressions of the user, always tied to evidence.

An impression is a short statement written by the assistant ("enjoys quiet,
outdoor hobbies"). It must cite at least one current memory. When any cited
memory is revised, retracted, expires or is forgotten, the impression becomes
`stale` and is no longer offered as a current view. Forgetting a topic deletes
the impressions that cite it. Users can list impressions with their evidence
and delete them at any time.

The checks are structural: a citation must exist and be current. Whether the
impression follows from the evidence cannot be decided here; a lexical
overlap check only warns when the impression shares no words with its evidence.
The optional table is created on the first save.
"""

import json
import uuid

from .codec import IntegrityError, checksum
from .core import canonical, instant, now_string
from .recall import terms

TABLE = "impressions"
MAX_TEXT = 500
MAX_CITES = 20


def installed(store):
    return store.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
    ).fetchone() is not None


def _cited(store, event_id, namespace, subject, clock):
    """Return (event, route) if `event_id` is a current memory of this subject."""
    row = store.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        return None, None
    event = store._read(row)
    c = event["candidate"]
    if (c["namespace"], c["subject"]) != (namespace, subject):
        return None, None
    head = store._head(row["route"])
    if (not head or head["id"] != event_id or head["status"] != "confirmed"
            or not store._live(head, clock)):
        return event, None
    return event, row["route"]


def save(store, namespace, subject, text, cites, *, now=None):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise ValueError(f"impression text must contain 1 to {MAX_TEXT} characters")
    cites = list(dict.fromkeys(cites or []))
    if not 1 <= len(cites) <= MAX_CITES:
        raise ValueError(f"an impression must cite 1 to {MAX_CITES} current memories")
    clock = instant(now or now_string())
    store.db.execute("BEGIN IMMEDIATE")
    try:
        citations, evidence_terms = [], set()
        for event_id in cites:
            event, route = _cited(store, event_id, namespace, subject, clock)
            if route is None:
                raise ValueError(f"cited memory {event_id} is not a current memory of this user")
            c = event["candidate"]
            citations.append({"event_id": event_id, "route": route,
                              "digest": checksum(canonical(event).encode())})
            evidence_terms |= terms(c["value"]) | terms(c["source"]) | terms(c["topic"])
        store.db.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE} (id TEXT PRIMARY KEY, namespace TEXT NOT NULL, "
            "subject TEXT NOT NULL, payload BLOB NOT NULL, digest TEXT NOT NULL)"
        )
        record = {"id": f"imp-{uuid.uuid4().hex[:12]}", "text": text.strip(),
                  "citations": citations, "created_at": clock.isoformat()}
        payload = canonical(record).encode()
        store.db.execute(f"INSERT INTO {TABLE} VALUES (?,?,?,?,?)",
                         (record["id"], namespace, subject, payload, checksum(payload)))
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise
    shared = terms(text) & evidence_terms
    result = {"id": record["id"], "status": "current", "citations": len(citations)}
    if not shared:
        result["warning"] = ("the impression shares no words with the cited memories; "
                             "check that it really follows from them")
    return result


def _records(store, namespace, subject):
    if not installed(store):
        return []
    out = []
    for row in store.db.execute(
        f"SELECT * FROM {TABLE} WHERE namespace=? AND subject=? ORDER BY rowid",
        (namespace, subject),
    ):
        if checksum(row["payload"]) != row["digest"]:
            raise IntegrityError("Corrupt impression; refusing to show it")
        out.append(json.loads(row["payload"]))
    return out


def listing(store, namespace, subject, *, now=None, include_stale=True):
    """Impressions with their evidence; `stale` ones are not current views."""
    clock = instant(now or now_string())
    out = []
    for record in _records(store, namespace, subject):
        evidence, stale = [], False
        for cite in record["citations"]:
            event, route = _cited(store, cite["event_id"], namespace, subject, clock)
            if route is None or checksum(canonical(event).encode()) != cite["digest"]:
                stale = True
                continue
            c = event["candidate"]
            evidence.append({"topic": c["topic"], "value": c["value"], "source": c["source"]})
        if stale and not include_stale:
            continue
        out.append({"id": record["id"], "text": record["text"],
                    "status": "stale" if stale else "current",
                    "created_at": record["created_at"], "evidence": evidence})
    return out


def forget(store, namespace, subject, impression_id=None):
    """Delete one impression, or all of this user's impressions."""
    if not installed(store):
        return 0
    if impression_id is None:
        return store.db.execute(f"DELETE FROM {TABLE} WHERE namespace=? AND subject=?",
                                (namespace, subject)).rowcount
    return store.db.execute(f"DELETE FROM {TABLE} WHERE id=? AND namespace=? AND subject=?",
                            (impression_id, namespace, subject)).rowcount


def purge_citing(store, route):
    """Inside the caller's transaction: delete impressions that cite `route`."""
    if not installed(store):
        return
    for row in list(store.db.execute(f"SELECT id, payload FROM {TABLE}")):
        record = json.loads(row["payload"])
        if any(c["route"] == route for c in record["citations"]):
            store.db.execute(f"DELETE FROM {TABLE} WHERE id=?", (row["id"],))
