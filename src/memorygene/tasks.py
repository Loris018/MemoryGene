"""Explicit, session-scoped task checkpoints with checked memory dependencies.

Task text is caller-authored data, never a new authority or confirmed user fact.
Conversation locators are not verified against a host transcript by this module.
The optional table is created only by save(), in the same transaction as the
checkpoint. Keeping it in the memory DB makes forget propagation atomic.
"""

import json
import re
import uuid
from datetime import timedelta

from .codec import IntegrityError, checksum, packed_complement, recover
from .core import canonical, instant, now_string

KINDS = {
    "goal",
    "constraint",
    "correction",
    "decision",
    "done",
    "open_question",
    "todo",
    "next_step",
}
TABLE = "task_checkpoints"


def installed(store):
    return (
        store.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
        ).fetchone()
        is not None
    )


def _text(value, label, maximum=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must contain 1 to {maximum} characters")


def validate_document(document):
    if not isinstance(document, dict) or set(document) != {"items", "sources"}:
        raise ValueError("Task document requires exactly items and sources")
    if len(canonical(document)) > 16000:
        raise ValueError("Task document exceeds 16000 characters")
    for label in ("items", "sources"):
        if not isinstance(document[label], list) or not 1 <= len(document[label]) <= 40:
            raise ValueError(f"{label} must contain 1 to 40 entries")
    sources = {}
    for source in document["sources"]:
        if not isinstance(source, dict):
            raise ValueError("Each source must be an object")
        _text(source.get("id"), "source id", 80)
        if source["id"] in sources:
            raise ValueError("Duplicate source id")
        kind = source.get("kind")
        if kind == "memory":
            if set(source) != {"id", "kind", "topic", "scope", "event_id"}:
                raise ValueError("Memory source requires id/kind/topic/scope/event_id")
            _text(source["topic"], "topic", 120)
            _text(source["event_id"], "event_id", 160)
            if source["scope"] not in {"persistent", "session"}:
                raise ValueError("Invalid memory source scope")
        elif kind == "conversation":
            if set(source) != {"id", "kind", "locator", "role"}:
                raise ValueError("Conversation source requires id/kind/locator/role")
            _text(source["locator"], "conversation locator", 256)
            if source["role"] not in {"user", "assistant", "tool"}:
                raise ValueError("Invalid conversation role")
        else:
            raise ValueError("Source kind must be memory or conversation")
        sources[source["id"]] = source
    used = set()
    for item in document["items"]:
        if not isinstance(item, dict) or set(item) != {"kind", "text", "source_ids"}:
            raise ValueError("Each task item requires kind/text/source_ids")
        if item["kind"] not in KINDS:
            raise ValueError("Invalid task item kind")
        _text(item["text"], "item text")
        refs = item["source_ids"]
        if not isinstance(refs, list) or not refs or len(refs) > 40:
            raise ValueError("Every item needs source_ids")
        for ref in refs:
            if not isinstance(ref, str) or ref not in sources:
                raise ValueError("Unknown source reference")
            used.add(ref)
    if used != set(sources):
        raise ValueError("Remove unused sources from the checkpoint")
    if not {"goal", "next_step"} <= {item["kind"] for item in document["items"]}:
        raise ValueError("Task needs a goal and a next_step")


def _route(store, namespace, subject, task, session):
    if not isinstance(task, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", task):
        raise ValueError("task must be a lowercase slug, at most 80 characters")
    _text(session, "session", 256)
    return store._route(namespace, subject, task, "session", session)


def _read(store, row):
    if checksum(row["payload"]) != row["digest"]:
        raise IntegrityError("Corrupt task checkpoint; use task-repair explicitly")
    record = json.loads(row["payload"])
    if record.get("schema") != "task-v1" or record.get("id") != row["id"]:
        raise IntegrityError("Task checkpoint identity/schema mismatch")
    route = _route(
        store, record["namespace"], record["subject"], record["task"], record["session"]
    )
    if row["route"] != route:
        raise IntegrityError("Task checkpoint routing mismatch")
    validate_document(record["document"])
    if instant(record["expires_at"]) <= instant(record["created_at"]):
        raise IntegrityError("Invalid task expiry")
    memory_ids = {
        s["id"] for s in record["document"]["sources"] if s["kind"] == "memory"
    }
    digests = record.get("source_digests")
    if not isinstance(digests, dict) or set(digests) != memory_ids:
        raise IntegrityError("Task source digest set mismatch")
    if any(
        not isinstance(d, str) or not re.fullmatch(r"[0-9a-f]{64}", d)
        for d in digests.values()
    ):
        raise IntegrityError("Invalid task source digest")
    return record


def _dependencies(store, record, now):
    checks, digests = [], {}
    for source in record["document"]["sources"]:
        if source["kind"] == "conversation":
            checks.append({"id": source["id"], "status": "caller_reference_unverified"})
            continue
        current = store.current(
            record["namespace"],
            record["subject"],
            source["topic"],
            scope=source["scope"],
            session=record["session"] if source["scope"] == "session" else "",
            now=now,
        )
        if current is None:
            status = "missing_or_expired"
        elif current["id"] != source["event_id"]:
            status = "changed"
        else:
            digest = checksum(canonical(current).encode())
            digests[source["id"]] = digest
            expected = record.get("source_digests", {}).get(source["id"])
            status = "changed" if expected and digest != expected else "current"
        checks.append({"id": source["id"], "status": status})
    return checks, digests


def _backup(store, raw):
    if store.protection == "none":
        return None
    return raw if store.protection == "copy" else packed_complement(raw)


def save(
    store,
    namespace,
    subject,
    task,
    session,
    document,
    *,
    previous_id=None,
    expires_at=None,
    now=None,
):
    """Validate sources and atomically append; updating requires the current ID."""
    validate_document(document)
    route = _route(store, namespace, subject, task, session)
    # Canonical identity must match core routing normalization.
    namespace, subject, task, _, session = store._route_parts(route)
    clock = instant(now or now_string())
    expiry = instant(expires_at) if expires_at else clock + timedelta(days=7)
    if not clock < expiry <= clock + timedelta(days=30):
        raise ValueError("Task expiry must be in the next 30 days (default 7 days)")
    record = {
        "schema": "task-v1",
        "id": "task-" + uuid.uuid4().hex,
        "namespace": namespace,
        "subject": subject,
        "task": task,
        "session": session,
        "created_at": clock.isoformat(),
        "expires_at": expiry.isoformat(),
        "previous_id": previous_id,
        "document": document,
    }
    store.db.execute("BEGIN IMMEDIATE")
    try:
        store.db.execute("""CREATE TABLE IF NOT EXISTS task_checkpoints (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
            route TEXT NOT NULL, payload BLOB NOT NULL, digest TEXT NOT NULL, backup BLOB)""")
        store.db.execute(
            "CREATE INDEX IF NOT EXISTS tasks_route ON task_checkpoints(route, seq)"
        )
        row = store.db.execute(
            "SELECT * FROM task_checkpoints WHERE route=? ORDER BY seq DESC LIMIT 1",
            (route,),
        ).fetchone()
        old = _read(store, row) if row else None
        if (old["id"] if old else None) != previous_id:
            raise ValueError(
                "Task version changed; read task-show and pass its checkpoint_id as --previous-id"
            )
        checks, record["source_digests"] = _dependencies(
            store, record, clock.isoformat()
        )
        if any(
            c["status"] not in {"current", "caller_reference_unverified"}
            for c in checks
        ):
            raise ValueError(
                "Task memory source is missing, changed or expired; rebuild from current evidence"
            )
        raw = canonical(record).encode()
        store.db.execute(
            "INSERT INTO task_checkpoints(id,route,payload,digest,backup) VALUES (?,?,?,?,?)",
            (record["id"], route, raw, checksum(raw), _backup(store, raw)),
        )
        store.db.commit()
        return {
            "status": "saved",
            "checkpoint_id": record["id"],
            "previous_id": previous_id,
            "expires_at": record["expires_at"],
            "source_checks": checks,
            "context_replaced": False,
        }
    except Exception:
        store.db.rollback()
        raise


def show(store, namespace, subject, task, session, *, now=None):
    route = _route(store, namespace, subject, task, session)
    if not installed(store):
        return {"status": "missing", "checkpoint": None}
    store.db.execute("BEGIN")
    try:
        row = store.db.execute(
            "SELECT * FROM task_checkpoints WHERE route=? ORDER BY seq DESC LIMIT 1",
            (route,),
        ).fetchone()
        result = _view(store, row, instant(now or now_string()))
        store.db.commit()
        return result
    except Exception:
        store.db.rollback()
        raise


def _view(store, row, clock):
    if row is None:
        return {"status": "missing", "checkpoint": None}
    record = _read(store, row)
    base = {
        "checkpoint_id": record["id"],
        "checkpoint": None,
        "context_replaced": False,
    }
    if instant(record["expires_at"]) <= clock:
        return {**base, "status": "expired"}
    checks, _ = _dependencies(store, record, clock.isoformat())
    if any(
        c["status"] not in {"current", "caller_reference_unverified"} for c in checks
    ):
        return {**base, "status": "stale", "source_checks": checks}
    return {
        **base,
        "status": "review_required",
        "checkpoint": record,
        "source_checks": checks,
        "note": "Caller-authored task data. Check source meaning, latest messages and current permissions before continuing.",
    }


def resume(
    store,
    namespace,
    subject,
    session,
    checkpoint_id,
    *,
    allow_cross_session=False,
    now=None,
):
    """Explicit transfer by exact ID; session-memory sources cannot be transferred.

    The flag records caller intent, not authentication or evidence of consent.
    A resumed record is returned for review, never silently persisted in the new session.
    """
    _text(session, "session", 256)
    _text(checkpoint_id, "checkpoint_id", 160)
    if not installed(store):
        return {"status": "missing", "checkpoint": None}
    store.db.execute("BEGIN")
    try:
        row = store.db.execute(
            "SELECT * FROM task_checkpoints WHERE id=?", (checkpoint_id,)
        ).fetchone()
        if row is not None:
            ns, subj, task, _, origin = store._route_parts(row["route"])
            requested = _route(store, namespace, subject, task, origin)
            if requested != row["route"]:
                row = None
            else:
                record = _read(store, row)
                if origin != session:
                    if not allow_cross_session:
                        raise ValueError(
                            "Cross-session task resume requires explicit --allow-cross-session"
                        )
                    if any(
                        s["kind"] == "memory" and s["scope"] == "session"
                        for s in record["document"]["sources"]
                    ):
                        raise ValueError(
                            "Cannot transfer a task depending on another session's memory"
                        )
                latest = store.db.execute(
                    "SELECT id FROM task_checkpoints WHERE route=? ORDER BY seq DESC LIMIT 1",
                    (row["route"],),
                ).fetchone()
                if latest["id"] != checkpoint_id:
                    store.db.commit()
                    return {"status": "superseded", "checkpoint": None}
        result = _view(store, row, instant(now or now_string()))
        store.db.commit()
        return result
    except Exception:
        store.db.rollback()
        raise


def forget(store, namespace, subject, task, session):
    route = _route(store, namespace, subject, task, session)
    if not installed(store):
        return 0
    return store.db.execute(
        "DELETE FROM task_checkpoints WHERE route=?", (route,)
    ).rowcount


def purge_dependents(store, memory_route):
    """Called inside MemoryStore.forget's transaction. Purge all affected versions.

    Inspect even expired/old checkpoints: their copies must not resurrect forgotten
    information. Corrupt relevant checkpoints block deletion until repaired or
    explicitly task-forgotten; never falsely report successful propagation.
    """
    if not installed(store):
        return
    ns, subj, *_ = store._route_parts(memory_route)
    affected = set()
    for row in store.db.execute("SELECT * FROM task_checkpoints"):
        parts = store._route_parts(row["route"])
        if parts[:2] != [ns, subj]:
            continue
        record = _read(store, row)
        for source in record["document"]["sources"]:
            if source["kind"] != "memory":
                continue
            dependency = store._route(
                ns,
                subj,
                source["topic"],
                source["scope"],
                record["session"] if source["scope"] == "session" else "",
            )
            if dependency == memory_route:
                affected.add(row["route"])
    for route in affected:
        store.db.execute("DELETE FROM task_checkpoints WHERE route=?", (route,))


def repair(store, namespace, subject, task, session, checkpoint_id):
    route = _route(store, namespace, subject, task, session)
    if not installed(store):
        raise KeyError("Task checkpoint not found")
    store.db.execute("BEGIN IMMEDIATE")
    try:
        row = store.db.execute(
            "SELECT * FROM task_checkpoints WHERE route=? AND id=?",
            (route, checkpoint_id),
        ).fetchone()
        if row is None:
            raise KeyError("Task checkpoint not found")
        raw = recover(row["payload"], row["backup"], row["digest"], store.protection)
        _read(store, dict(row) | {"payload": raw})
        store.db.execute(
            "UPDATE task_checkpoints SET payload=?,backup=? WHERE id=?",
            (raw, _backup(store, raw), checkpoint_id),
        )
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise


def verify(store):
    """Integrity/lineage only; a stale dependency is normal, not corruption."""
    if not installed(store):
        return {"checkpoints": 0, "problems": []}
    rows = list(store.db.execute("SELECT * FROM task_checkpoints ORDER BY seq"))
    previous, problems = {}, []
    for row in rows:
        try:
            record = _read(store, row)
            if record["previous_id"] != previous.get(row["route"]):
                raise IntegrityError("Broken task version chain")
        except (ValueError, KeyError, TypeError) as exc:
            problems.append(
                {"kind": "task", "event_id": row["id"], "problem": str(exc)}
            )
        previous[row["route"]] = row["id"]
    return {"checkpoints": len(rows), "problems": problems}
