"""Routing collisions (valid pairs), duplicate TTL, timestamp parsing (baseline)."""
from memorygene import Candidate, MemoryStore
import memorygene
print("module:", memorygene.__file__)
NOW = "2026-10-24T10:00:00+00:00"
def cand(value="A", **kw):
    f = dict(namespace="demo", subject="u", topic="t", value=value, source="fiction",
             at="2026-10-01T00:00:00+00:00")
    f.update(kw); return Candidate(**f)

print("\n=== G. routing collision probes (valid routing tuples) ===")
s = MemoryStore()
pairs = [
    (("a.b","c","d","persistent",""), ("a","b.c","d","persistent","")),
    (("a","b","c","persistent",""), ("a","b","c","session","x")),
    (("a","b","c","session","x"), ("a","b","c","session","x ")),
    (('x"y',"s","t","persistent",""), ('x\\"y',"s","t","persistent","")),
    (("é","s","t","persistent",""), ("e\u0301","s","t","persistent","")),
    (("a","b","c","persistent",""), ("a","b","c","persistent","x")),
]
for a,b in pairs:
    try:
        ra, rb = s._route(*a), s._route(*b)
        print(f"  {a} vs {b} -> {'SAME (intentional NFC merge)' if ra==rb else 'distinct'}")
    except ValueError as e:
        print(f"  {a} vs {b} -> rejected: {e}")
try:
    s._route("a", 1, "c")
except ValueError as e:
    print("  non-string routing rejected:", e)
s.close()

print("\n=== E-fixed. duplicate with live head does not extend TTL/head ===")
s = MemoryStore()
r1 = s.ingest(cand("A", expires_at="2026-10-20T00:00:00Z"), "1", now="2026-10-02T00:00:00Z")
r2 = s.ingest(cand("A"), "2", now="2026-10-02T00:00:00Z")
print(" first:", r1["status"], "| retry same value:", r2["status"], "| head:", s.current("demo","u","t",now="2026-10-02T00:00:00Z")["id"])
print(" current at 2026-10-21 (after TTL):", s.current("demo","u","t",now="2026-10-21T00:00:00Z"))
print(" history at 2026-10-21 (expired filtered):", s.history("demo","u","t",now="2026-10-21T00:00:00Z"))
s.close()

print("\n=== J-fixed. equal evidence timestamps + explicit assert (different values) ===")
s = MemoryStore()
s.ingest(cand("A", at="2026-10-01T00:00:00Z"), "1", now=NOW)
r = s.ingest(cand("B", at="2026-10-01T00:00:00Z"), "2", now=NOW)
print(" status:", r["status"], "| current:", s.current("demo","u","t",now=NOW)["candidate"]["value"])
s.close()

print("\n=== Timestamp parsing edge cases ===")
from memorygene.core import instant
for v in ("2026-10-24T10:00:00Z","2026-10-24T10:00:00+00:00","2026-10-24T10:00:00+0000","2026-10-24T10:00:00+00",
          "2026-10-24T10:00:00","2026-10-24T10:00:00z","2026-10-24 10:00:00+00:00","20261024T100000+0000"):
    try:
        print(f"  {v!r:40} -> {instant(v).isoformat()}")
    except Exception as e:
        print(f"  {v!r:40} -> {type(e).__name__}: {e}")

print("\n=== future evidence / now-naive guards ===")
s = MemoryStore()
try:
    s.ingest(cand(at="2026-10-25T00:00:00Z"), "1", now=NOW)
except ValueError as e:
    print(" future evidence rejected:", e)
try:
    s.ingest(cand(), "1", now="2026-10-24T10:00:00")
except ValueError as e:
    print(" naive now rejected:", e)
try:
    s.ingest(cand(), 123, now=NOW)
except ValueError as e:
    print(" non-string event_id rejected:", e)
s.close()

print("\n=== event_id reuse across routes ===")
s = MemoryStore()
s.ingest(cand(), "same", now=NOW)
try:
    s.ingest(cand(subject="other"), "same", now=NOW)
except ValueError as e:
    print(" reuse across routes rejected:", e)
s.close()
