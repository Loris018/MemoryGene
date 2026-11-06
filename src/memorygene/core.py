"""Structured policy core. Natural-language extraction is an external adapter."""

import json
import math
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .codec import (
    IntegrityError,
    checksum,
    complement,
    decode,
    encode,
    packed_complement,
    recover,
)


def canonical(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def instant(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Timestamp must be timezone-aware ISO text")
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return t.astimezone(timezone.utc)


def now_string() -> str:
    return datetime.now(timezone.utc).isoformat()


INTENTS = {"assert", "change", "correct", "supplement", "retract"}
# Events a head may point to. A ``retracted`` head means the user withdrew the
# value: the slot has no current value, and its history is kept.
HEAD_STATUSES = {"confirmed", "retracted"}


@dataclass(frozen=True)
class Candidate:
    namespace: str
    subject: str
    topic: str
    value: str
    source: str
    at: str
    certainty: str = "explicit"  # explicit, uncertain, inferred
    intent: str = "assert"  # assert, change, correct, supplement, retract
    importance: float = 0.7
    scope: str = "persistent"
    session: str = ""
    expires_at: str | None = None
    sensitive: bool = False
    consent: bool = False

    def __post_init__(self):
        # Identity/value are compared byte-exactly later, so normalise their
        # Unicode composition once here. Evidence text (`source`) stays verbatim.
        for name in ("namespace", "subject", "topic", "value"):
            value = getattr(self, name)
            if isinstance(value, str):
                object.__setattr__(self, name, unicodedata.normalize("NFC", value))

    def validate(self):
        for name in ("namespace", "subject", "topic", "value", "source", "at"):
            if (
                not isinstance(getattr(self, name), str)
                or not getattr(self, name).strip()
            ):
                raise ValueError(f"{name} must be nonempty text")
        if self.certainty not in {"explicit", "uncertain", "inferred"}:
            raise ValueError("Invalid certainty")
        if self.intent not in INTENTS:
            raise ValueError("Invalid intent")
        if isinstance(self.importance, bool) or not isinstance(
            self.importance, (int, float)
        ):
            raise ValueError("Invalid importance")
        if not 0 <= self.importance <= 1 or not math.isfinite(self.importance):
            raise ValueError("Invalid importance")
        if self.scope not in {"persistent", "session"} or not isinstance(
            self.session, str
        ):
            raise ValueError("Invalid scope/session")
        if self.scope == "session":
            if not self.session.strip():
                raise ValueError("Session scope requires a nonblank session ID")
        elif self.session:
            raise ValueError("Persistent scope forbids a session ID")
        if not isinstance(self.sensitive, bool) or not isinstance(self.consent, bool):
            raise ValueError("sensitive/consent must be booleans")
        start = instant(self.at)
        if self.expires_at is not None and instant(self.expires_at) <= start:
            raise ValueError("Expiry must be later than evidence timestamp")


def routing(namespace, subject, topic, scope="persistent", session="") -> str:
    parts = [namespace, subject, topic, scope, session]
    if any(not isinstance(p, str) for p in parts):
        raise ValueError("Routing fields must be strings")
    if not all(p.strip() for p in parts[:3]):
        raise ValueError("Empty routing field")
    if scope == "session":
        if not session.strip():
            raise ValueError("Session scope requires a nonblank session ID")
    elif scope == "persistent":
        if session:
            raise ValueError("Persistent scope forbids a session ID")
    else:
        raise ValueError("Invalid scope/session")
    return canonical([unicodedata.normalize("NFC", p) for p in parts])


class MemoryStore:
    def __init__(self, path=":memory:", *, index="complement", protection="complement"):
        if index not in {"plain", "complement"} or protection not in {
            "none",
            "copy",
            "complement",
        }:
            raise ValueError("Invalid index/protection")
        self.index, self.protection = index, protection
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        # Never adopt an unrelated SQLite file: only create/use tables in a file
        # whose existing tables are already part of the MemoryGene schema.
        existing_tables = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        unexpected = existing_tables - {
            "config",
            "events",
            "heads",
            "sqlite_sequence",
            "task_checkpoints",
        }
        # A MemoryGene store always has the three core tables. Requiring them
        # before creating anything prevents an unrelated SQLite file from being
        # adopted just because it happens to contain a table whose name is part
        # of the current schema (e.g. the optional task extension).
        missing_core = {"config", "events", "heads"} - existing_tables
        if existing_tables and missing_core:
            self.db.close()
            raise ValueError(
                "Not a MemoryGene database; refusing to adopt a SQLite file "
                f"without core tables {sorted(missing_core)}"
            )
        if unexpected:
            self.db.close()
            raise ValueError(
                "Not a MemoryGene database; refusing to adopt a foreign SQLite "
                f"file with tables {sorted(unexpected)}"
            )
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE NOT NULL, route TEXT NOT NULL,
                payload BLOB NOT NULL, digest TEXT NOT NULL, backup BLOB);
            CREATE INDEX IF NOT EXISTS events_route ON events(route, seq);
            CREATE TABLE IF NOT EXISTS heads (
                route TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id));
        """)
        expected = {
            "schema": "1",
            "codec": "dna-v1",
            "index": index,
            "protection": protection,
        }
        self.db.execute("BEGIN IMMEDIATE")
        try:
            config = dict(self.db.execute("SELECT key,value FROM config"))
            if config and config != expected:
                raise ValueError(
                    "Database schema/config mismatch; explicit migration required"
                )
            if not config:
                if self.db.execute("SELECT 1 FROM events LIMIT 1").fetchone():
                    raise ValueError("Missing configuration on nonempty database")
                self.db.executemany("INSERT INTO config VALUES (?,?)", expected.items())
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _route(self, *args):
        key = routing(*args)
        return complement(encode(key.encode())) if self.index == "complement" else key

    def _read(self, row):
        if row is None:
            return None
        # Reads fail closed; repair is an explicit separate operation.
        if checksum(row["payload"]) != row["digest"]:
            raise IntegrityError("Corrupt event; call repair explicitly")
        event = json.loads(row["payload"])
        c = Candidate(**event["candidate"])
        c.validate()
        if (
            event["id"] != row["id"]
            or self._route(c.namespace, c.subject, c.topic, c.scope, c.session)
            != row["route"]
        ):
            raise IntegrityError("Event identity/routing mismatch")
        return event

    def _head(self, route):
        row = self.db.execute(
            "SELECT e.* FROM heads h JOIN events e ON e.id=h.event_id WHERE h.route=?",
            (route,),
        ).fetchone()
        if row is not None and row["route"] != route:
            raise IntegrityError("Head points outside requested memory route")
        event = self._read(row)
        if event and event["status"] not in HEAD_STATUSES:
            raise IntegrityError("Head points to unconfirmed evidence")
        return event

    @staticmethod
    def _live(event, now):
        expiry = event["candidate"]["expires_at"]
        return expiry is None or instant(expiry) > now

    def ingest(
        self,
        c: Candidate,
        event_id: str,
        *,
        now: str | None = None,
        resolves: str | None = None,
        update: str = "confirm",
    ):
        """Apply the state machine to one candidate.

        ``update`` chooses how a newer explicit assertion of a different value
        is handled when the user did not say it is a change. ``confirm`` (the
        default) holds it as ``conflict`` until the user confirms. ``latest``
        accepts it as the new current value and marks the event with
        ``policy: latest``; it is meant for unattended use where nobody can be
        asked. Supplements, uncertain statements and older evidence behave the
        same in both modes.
        """
        if update not in {"confirm", "latest"}:
            raise ValueError("update must be confirm or latest")
        c.validate()
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Nonempty event_id required")
        clock = instant(now or now_string())
        if instant(c.at) > clock:
            raise ValueError("Future evidence is not accepted")
        route = self._route(c.namespace, c.subject, c.topic, c.scope, c.session)
        # A write lock protects compare-and-update across independent connections.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self._read(
                self.db.execute(
                    "SELECT * FROM events WHERE id=?", (event_id,)
                ).fetchone()
            )
            if prior:
                if prior["candidate"] != asdict(c) or prior["resolves"] != resolves:
                    raise ValueError("event_id reused with different content")
                self.db.commit()
                return prior
            if resolves is not None:
                target_row = self.db.execute(
                    "SELECT * FROM events WHERE id=?", (resolves,)
                ).fetchone()
                target = self._read(target_row)
                if (
                    not target
                    or target_row["route"] != route
                    or target["status"] not in {"pending", "conflict"}
                    or target["candidate"]["value"] != c.value
                ):
                    raise ValueError(
                        "Resolution requires pending/conflicting evidence on the same route and value"
                    )
                existing = [
                    self._read(r)
                    for r in self.db.execute(
                        "SELECT * FROM events WHERE route=?", (route,)
                    )
                ]
                if any(e["resolves"] == resolves for e in existing):
                    raise ValueError("Evidence already resolved")
            if c.sensitive and not c.consent:
                status = "rejected_sensitive"
            elif c.scope == "persistent" and c.importance < 0.5:
                status = "discarded"
            elif c.expires_at and instant(c.expires_at) <= clock:
                status = "expired"
            else:
                status = None
            if status:
                self.db.commit()
                # Rejected evidence is never persisted, including in a backup.
                return {"id": event_id, "status": status, "previous_id": None}
            head = self._head(route)
            live = (
                head
                if head and head["status"] == "confirmed" and self._live(head, clock)
                else None
            )
            accepted_by_policy = False
            if c.intent == "retract":
                # Withdraws the current value; it must name that value.
                if resolves is not None:
                    raise ValueError("A retraction cannot resolve other evidence")
                if c.certainty != "explicit":
                    status = "pending"
                elif live and live["candidate"]["value"] == c.value:
                    status = "retracted"
                else:
                    self.db.commit()
                    return {"id": event_id, "status": "nothing_to_retract",
                            "previous_id": None}
            elif c.certainty != "explicit":
                status = "pending"
            elif live and live["candidate"]["value"] == c.value:
                status = "duplicate"
            elif (
                head
                and (c.value != head["candidate"]["value"] or head["status"] == "retracted")
                and instant(c.at) < instant(head["candidate"]["at"])
            ):
                # Older evidence never overrides a newer version or retraction.
                status = "conflict"
            elif c.intent == "supplement":
                # "X is nice too" never sets the slot, even when it is empty.
                status = "pending"
            elif live and c.intent not in {"change", "correct"}:
                if update == "latest":
                    status, accepted_by_policy = "confirmed", True
                else:
                    status = "conflict"
            else:
                status = "confirmed"
            if resolves is not None and status not in {"confirmed", "duplicate"}:
                raise ValueError("Resolution needs explicit, current confirmation")
            event = {
                "id": event_id,
                "status": status,
                "candidate": asdict(c),
                "previous_id": head["id"] if head else None,
                "schema": 1,
                "recorded_at": clock.isoformat(),
                "resolves": resolves,
            }
            if accepted_by_policy:
                # Recorded so history shows the change was not stated as one.
                event["policy"] = "latest"
            payload = canonical(event).encode()
            backup = (
                None
                if self.protection == "none"
                else (
                    payload if self.protection == "copy" else packed_complement(payload)
                )
            )
            self.db.execute(
                "INSERT INTO events(id,route,payload,digest,backup) VALUES (?,?,?,?,?)",
                (event_id, route, payload, checksum(payload), backup),
            )
            if status in HEAD_STATUSES:
                self.db.execute(
                    "INSERT INTO heads VALUES (?,?) ON CONFLICT(route) DO UPDATE SET event_id=excluded.event_id",
                    (route, event_id),
                )
            self.db.commit()
            return event
        except Exception:
            self.db.rollback()
            raise

    def current(
        self, namespace, subject, topic, *, scope="persistent", session="", now=None
    ):
        route = self._route(namespace, subject, topic, scope, session)
        event = self._head(route)
        if not event or event["status"] != "confirmed":
            return None
        return event if self._live(event, instant(now or now_string())) else None

    def history(
        self, namespace, subject, topic, *, scope="persistent", session="", now=None
    ):
        route = self._route(namespace, subject, topic, scope, session)
        clock = instant(now or now_string())
        events = [
            self._read(r)
            for r in self.db.execute(
                "SELECT * FROM events WHERE route=? ORDER BY seq", (route,)
            )
        ]
        return [e for e in events if self._live(e, clock)]

    def _route_parts(self, route):
        """Decode a stored routing key back into its five canonical fields."""
        try:
            if self.index == "complement":
                raw = decode(complement(route))
            else:
                raw = route.encode()
            parts = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise IntegrityError("Unreadable routing key; refusing to guess") from None
        if (
            not isinstance(parts, list)
            or len(parts) != 5
            or not all(isinstance(p, str) for p in parts)
        ):
            raise IntegrityError("Unreadable routing key; refusing to guess")
        return parts

    def topics(self, namespace, subject, *, now=None, visible_session=None):
        """List the subject's topics with current-state and evidence counts.

        This is a read-only index for recall. It scans and integrity-checks the
        stored routes, so a corrupt database fails closed instead of returning a
        silently incomplete list. It never creates or resurrects a current value.
        ``visible_session`` limits recall to persistent routes and that session;
        an empty string exposes persistent routes only. None retains the full
        administrative index for existing core/CLI callers (not access control).
        """
        clock = instant(now or now_string())
        rows = list(
            self.db.execute("SELECT DISTINCT route FROM events ORDER BY route")
        )
        out = []
        for row in rows:
            route = row["route"]
            ns, subj, topic, scope, session = self._route_parts(route)
            if ns != namespace or subj != subject:
                continue
            if visible_session is not None and scope == "session" and (
                not visible_session or session != visible_session
            ):
                continue
            events = [
                self._read(r)
                for r in self.db.execute(
                    "SELECT * FROM events WHERE route=? ORDER BY seq", (route,)
                )
            ]
            head = self._head(route)
            live = (
                head
                if head and head["status"] == "confirmed" and self._live(head, clock)
                else None
            )
            counts = {"confirmed": 0, "pending": 0, "conflict": 0, "duplicate": 0,
                      "retracted": 0}
            for event in events:
                counts[event["status"]] = counts.get(event["status"], 0) + 1
            out.append(
                {
                    "namespace": ns,
                    "subject": subj,
                    "topic": topic,
                    "scope": scope,
                    "session": session,
                    "status": (
                        "current" if live
                        else "retracted" if head and head["status"] == "retracted"
                        else "expired" if head else "unconfirmed"
                    ),
                    "current": (
                        {
                            "id": live["id"],
                            "value": live["candidate"]["value"],
                            "at": live["candidate"]["at"],
                            "expires_at": live["candidate"].get("expires_at"),
                        }
                        if live
                        else None
                    ),
                    "evidence": counts,
                }
            )
        out.sort(key=lambda item: (item["topic"], item["scope"], item["session"]))
        return out

    def verify(self):
        """Scan *all* stored evidence and head pointers for detectable damage.

        Normal reads only validate the records they touch, so tampered metadata
        can make one topic look empty or make an old version look current. This
        full scan reports:

        * every event whose bytes, digest, identity or routing no longer verify;
        * every head that points at a missing/unreadable event, unconfirmed
          evidence, or evidence whose route differs from the head route;
        * every route that has confirmed evidence but no head, and every head
          that is not the latest confirmed event of its route (which catches a
          head rolled back to an older version).

        It is an explicit audit operation; it never repairs or changes state.
        Deleting a historical non-head event is not detectable here (sequence
        gaps also occur for legitimate rolled-back transactions).
        """
        problems = []
        events = list(self.db.execute("SELECT * FROM events ORDER BY seq"))
        seen = {}
        latest_confirmed = {}
        for row in events:
            try:
                event = self._read(row)
            except IntegrityError as exc:
                problems.append(
                    {
                        "kind": "event",
                        "event_id": row["id"],
                        "problem": str(exc),
                    }
                )
                continue
            seen[row["id"]] = event
            if event["status"] in HEAD_STATUSES:
                previous = latest_confirmed.get(row["route"])
                if previous is None or row["seq"] > previous[0]:
                    latest_confirmed[row["route"]] = (row["seq"], row["id"])
        heads = list(self.db.execute("SELECT route, event_id FROM heads"))
        head_routes = set()
        for head in heads:
            head_routes.add(head["route"])
            event = seen.get(head["event_id"])
            if event is None:
                problems.append(
                    {
                        "kind": "head",
                        "route": head["route"],
                        "event_id": head["event_id"],
                        "problem": "head points to a missing or unreadable event",
                    }
                )
                continue
            if event["status"] not in HEAD_STATUSES:
                problems.append(
                    {
                        "kind": "head",
                        "route": head["route"],
                        "event_id": head["event_id"],
                        "problem": "head points to unconfirmed evidence",
                    }
                )
            candidate = Candidate(**event["candidate"])
            expected = self._route(
                candidate.namespace,
                candidate.subject,
                candidate.topic,
                candidate.scope,
                candidate.session,
            )
            if expected != head["route"]:
                problems.append(
                    {
                        "kind": "head",
                        "route": head["route"],
                        "event_id": head["event_id"],
                        "problem": "head route does not match its event's routing fields",
                    }
                )
            latest = latest_confirmed.get(expected)
            if latest is not None and latest[1] != head["event_id"]:
                problems.append(
                    {
                        "kind": "head",
                        "route": head["route"],
                        "event_id": head["event_id"],
                        "problem": (
                            "head is not the latest confirmed event of its route "
                            "(rolled back or inconsistent)"
                        ),
                    }
                )
        for route, (_, event_id) in latest_confirmed.items():
            if route not in head_routes:
                problems.append(
                    {
                        "kind": "head",
                        "route": route,
                        "event_id": event_id,
                        "problem": (
                            "route has confirmed evidence but no head "
                            "(missing head or silently dropped current version)"
                        ),
                    }
                )
        from .tasks import verify as verify_tasks

        task_report = verify_tasks(self)
        problems.extend(task_report["problems"])
        return {
            "ok": not problems,
            "events": len(events),
            "task_checkpoints": task_report["checkpoints"],
            "heads": self.db.execute("SELECT COUNT(*) FROM heads").fetchone()[0],
            "problems": problems,
            "scan": "full",
        }

    def repair(self, event_id):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM events WHERE id=?", (event_id,)
            ).fetchone()
            if row is None:
                raise KeyError(event_id)
            restored = recover(
                row["payload"], row["backup"], row["digest"], self.protection
            )
            # Check identity/routing before changing bytes.
            self._read(dict(row) | {"payload": restored})
            backup = (
                None
                if self.protection == "none"
                else (
                    restored
                    if self.protection == "copy"
                    else packed_complement(restored)
                )
            )
            self.db.execute(
                "UPDATE events SET payload=?,backup=? WHERE id=?",
                (restored, backup, event_id),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def forget(self, namespace, subject, topic, *, scope="persistent", session=""):
        route = self._route(namespace, subject, topic, scope, session)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            from .tasks import purge_dependents

            purge_dependents(self, route)
            self.db.execute("DELETE FROM heads WHERE route=?", (route,))
            count = self.db.execute(
                "DELETE FROM events WHERE route=?", (route,)
            ).rowcount
            self.db.commit()
            return count
        except Exception:
            self.db.rollback()
            raise
