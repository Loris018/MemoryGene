"""State-machine edge cases vs docs/DESIGN.md (baseline 4bb7306)."""
import json
from memorygene import Candidate, MemoryStore
import memorygene
print("module:", memorygene.__file__)
NOW = "2026-10-24T10:00:00+00:00"

def cand(value="A", **kw):
    f = dict(namespace="demo", subject="u", topic="t", value=value,
             source="fiction", at="2026-10-01T00:00:00+00:00")
    f.update(kw); return Candidate(**f)

print("\n=== A. expired head + OLDER same-value explicit assert ===")
s = MemoryStore()
s.ingest(cand("A", expires_at="2026-10-05T00:00:00Z"), "1", now="2026-10-02T00:00:00Z")
print(" current at NOW:", s.current("demo","u","t",now=NOW))
r = s.ingest(cand("A", at="2026-09-01T00:00:00Z"), "2", now=NOW)
print(" status:", r["status"], "| previous_id:", r["previous_id"])
print(" current after:", None if s.current("demo","u","t",now=NOW) is None else s.current("demo","u","t",now=NOW)["id"])
print(" DESIGN table: cond6 requires value-different; cond9 'no live old value' => confirmed. Observed:", r["status"])
s.close()

print("\n=== B. expired head + NEWER same-value explicit assert ===")
s = MemoryStore()
s.ingest(cand("A", expires_at="2026-10-05T00:00:00Z"), "1", now="2026-10-02T00:00:00Z")
r = s.ingest(cand("A", at="2026-10-10T00:00:00Z"), "2", now=NOW)
print(" status:", r["status"], "previous_id:", r["previous_id"], "| current:", s.current("demo","u","t",now=NOW)["id"])
s.close()

print("\n=== C. expired head + NEWER different-value explicit assert ===")
s = MemoryStore()
s.ingest(cand("A", expires_at="2026-10-05T00:00:00Z"), "1", now="2026-10-02T00:00:00Z")
r = s.ingest(cand("B", at="2026-10-10T00:00:00Z"), "2", now=NOW)
print(" status:", r["status"], "(doc cond9: no live old value => confirmed?) | current:", s.current("demo","u","t",now=NOW))
s.close()

print("\n=== D. supplement on empty slot explicit ===")
s = MemoryStore(); r = s.ingest(cand("B", intent="supplement"), "1", now=NOW)
print(" status:", r["status"], "(doc: explicit supplement on empty slot => confirmed)")
s.close()

print("\n=== E. duplicate does not extend TTL / change head ===")
s = MemoryStore()
s.ingest(cand("A", expires_at="2026-10-20T00:00:00Z"), "1", now=NOW)
r = s.ingest(cand("A"), "2", now=NOW)
print(" duplicate status:", r["status"], "| current at 10-25:", None if s.current("demo","u","t",now="2026-10-25T00:00:00Z") is None else "value")
s.close()

print("\n=== F. resolve pending with duplicate value ===")
s = MemoryStore()
s.ingest(cand("A"), "1", now=NOW)
s.ingest(cand("A", certainty="uncertain", at="2026-10-02T00:00:00Z"), "2", now=NOW)
r = s.ingest(cand("A", at="2026-10-03T00:00:00Z"), "3", now=NOW, resolves="2")
print(" status:", r["status"], "resolves:", r["resolves"])
h = s.history("demo","u","t",now=NOW)
print(" history:", [(e["id"], e["status"], e["resolves"]) for e in h], "(target still pending?)")
s.close()

print("\n=== G. resolve target from another route / gone ===")
s = MemoryStore()
s.ingest(cand("A", certainty="uncertain"), "1", now=NOW)
try:
    s.ingest(cand("A", intent="change", subject="other"), "2", now=NOW, resolves="1")
except ValueError as e:
    print(" cross-subject resolve rejected:", e)
try:
    s.ingest(cand("A", intent="change"), "3", now=NOW, resolves="ghost")
except ValueError as e:
    print(" ghost resolve rejected:", e)
s.close()

print("\n=== H. conflict status events never head, but persist ===")
s = MemoryStore()
s.ingest(cand("A"), "1", now=NOW)
r = s.ingest(cand("B"), "2", now=NOW)
print(" status:", r["status"], "previous_id:", r["previous_id"], "current:", s.current("demo","u","t",now=NOW)["id"])
print(" history ids:", [e["id"] for e in s.history("demo","u","t",now=NOW)])
s.close()

print("\n=== I. retry after forget recreates deleted evidence (no tombstone) ===")
s = MemoryStore()
s.ingest(cand("A"), "1", now=NOW)
s.forget("demo","u","t")
r = s.ingest(cand("A"), "1", now=NOW)
print(" after forget, re-ingest same event_id/content ->", r["status"], "| history:", [e["id"] for e in s.history("demo","u","t",now=NOW)])
s.close()

print("\n=== J. equal evidence timestamps, different values: later write overwrites ===")
s = MemoryStore()
s.ingest(cand("A", at="2026-10-01T00:00:00Z"), "1", now=NOW)
r = s.ingest(cand("B", intent="change", at="2026-10-01T00:00:00Z"), "2", now=NOW)
print(" status:", r["status"], "| current:", s.current("demo","u","t",now=NOW)["candidate"]["value"], "(same timestamp, no conflict)")
s.close()

print("\n=== K. NFC/NFD in VALUE (routing is NFC-normalized, value is not) ===")
s = MemoryStore()
s.ingest(cand("caf\u00e9"), "1", now=NOW)  # NFC
r = s.ingest(cand("cafe\u0301", at="2026-10-02T00:00:00Z"), "2", now=NOW)  # NFD, canonically equal
print(" status:", r["status"], "| current:", repr(s.current("demo","u","t",now=NOW)["candidate"]["value"]))
s.close()

print("\n=== L. whitespace-only session for session scope ===")
s = MemoryStore()
try:
    s.ingest(cand("A", scope="session", session=" "), "1", now=NOW)
    print(" session=' ' accepted as session-scoped memory; current(scope=session,session=' '):",
          s.current("demo","u","t",scope="session",session=" ",now=NOW)["id"])
except ValueError as e:
    print(" rejected:", e)
s.close()

print("\n=== M. huge value / event id lengths (no limits) ===")
s = MemoryStore()
big = "x"*100000
r = s.ingest(cand(big), "e"*1000, now=NOW)
print(" status:", r["status"], "payload bytes:", s.db.execute("SELECT length(payload) FROM events").fetchone()[0])
s.close()
