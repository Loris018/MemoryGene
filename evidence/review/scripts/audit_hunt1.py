"""Audit scripts against baseline 4bb7306: fail-closed gaps & docs table divergence."""
import json, sys
from memorygene import Candidate, MemoryStore
import memorygene
from memorygene.codec import IntegrityError, checksum

print("module:", memorygene.__file__)
NOW = "2026-10-24T10:00:00+00:00"

def cand(value="A", **kw):
    f = dict(namespace="demo", subject="u", topic="t", value=value,
             source="fiction", at="2026-10-01T00:00:00+00:00")
    f.update(kw)
    return Candidate(**f)

def case(title, fn):
    print("\n---", title)
    try:
        fn()
    except Exception as e:
        print(" raised", type(e).__name__, ":", e)

# 1. dangling head pointer: heads.event_id -> missing event (FK not enforced on direct UPDATE? PRAGMA on, but UPDATE heads set event_id='ghost' violates FK -> sqlite3.IntegrityError)
def dangling_head():
    s = MemoryStore(); s.ingest(cand(), "1", now=NOW)
    try:
        s.db.execute("UPDATE heads SET event_id='ghost'")
        print(" direct UPDATE allowed (FK not enforced?)")
    except Exception as e:
        print(" UPDATE rejected by FK:", type(e).__name__, e)
        # simulate a corrupted head that still satisfies FK: point to a real event of another route
        s.ingest(cand(value="B", subject="other"), "2", now=NOW)
        s.db.execute("UPDATE heads SET event_id='2' WHERE event_id='1'")
        try:
            print(" current ->", s.current("demo","u","t",now=NOW))
        except IntegrityError as e:
            print(" cross-route head -> IntegrityError (expected):", e)
        # delete the referenced event directly to simulate dangling head (FK would block; disable FK on this connection)
        s.db.execute("PRAGMA foreign_keys=OFF")
        s.db.execute("DELETE FROM events WHERE id='2'")
        s.db.execute("PRAGMA foreign_keys=ON")
        try:
            print(" current with dangling head ->", s.current("demo","u","t",now=NOW))
        except IntegrityError as e:
            print(" dangling head -> IntegrityError:", e)
    s.close()

# 2. route-column corruption of a NON-head event -> history silently drops it (fail open)
def route_corruption():
    s = MemoryStore()
    s.ingest(cand(), "1", now=NOW)
    s.ingest(cand("B", intent="change", at="2026-10-10T00:00:00Z"), "2", now=NOW)
    print(" history before:", [e["id"] for e in s.history("demo","u","t",now=NOW)])
    s.db.execute("UPDATE events SET route='CORRUPT' WHERE id='1'")
    try:
        h = s.history("demo","u","t",now=NOW)
        print(" history after non-head route corruption:", [e["id"] for e in h], " (silently dropped id=1)")
    except IntegrityError as e:
        print(" history -> IntegrityError:", e)
    # what does current do? head id=2 intact
    print(" current:", s.current("demo","u","t",now=NOW)["id"])
    s.close()

# 3. head route corruption -> current silently None
def head_route_corruption():
    s = MemoryStore(); s.ingest(cand(), "1", now=NOW)
    s.db.execute("UPDATE heads SET route='CORRUPT'")
    try:
        print(" current after head route corruption ->", s.current("demo","u","t",now=NOW))
    except IntegrityError as e:
        print(" current -> IntegrityError:", e)
    try:
        print(" history still:", [e["id"] for e in s.history("demo","u","t",now=NOW)])
    except Exception as e:
        print(" history ->", type(e).__name__, e)
    s.close()

# 4. events.route corruption of the head's row: join by id still finds it -> fail closed?
def head_event_route_corruption():
    s = MemoryStore(); s.ingest(cand(), "1", now=NOW)
    s.db.execute("UPDATE events SET route='CORRUPT' WHERE id='1'")
    try:
        print(" current ->", s.current("demo","u","t",now=NOW))
    except IntegrityError as e:
        print(" current -> IntegrityError (fail closed):", e)
    s.close()

print("\n===== docs table divergence: expired head + older SAME-value explicit evidence =====")
def expired_head_same_value():
    s = MemoryStore()
    s.ingest(cand("A", expires_at="2026-10-05T00:00:00Z"), "1", now=NOW)
    print(" head live?", s.current("demo","u","t",now=NOW))
    # explicit assert same value A, evidence time BEFORE head's at (2026-09-01 < 2026-10-01)
    r = s.ingest(cand("A", at="2026-09-01T00:00:00Z"), "2", now=NOW)
    print(" status:", r["status"], " previous_id:", r["previous_id"])
    print(" current now:", s.current("demo","u","t",now=NOW))
    print(" DESIGN table implies condition 6 requires different value, condition 9 'no live old value' => confirmed")
    s.close()

case("1 dangling/cross head", dangling_head)
case("2 non-head route corruption", route_corruption)
case("3 head route corruption", head_route_corruption)
case("4 head event route corruption", head_event_route_corruption)
case("expired-head same value older evidence", expired_head_same_value)
