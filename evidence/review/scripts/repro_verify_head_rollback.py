"""FINAL audit P1 repro: verify() does not detect two heads-metadata damage classes
advertised as detectable: (1) head rolled back to an older confirmed event (old
value silently becomes current again), (2) heads row deleted (current silently null).
Uses the final tree (PYTHONPATH=<final tree>/src)."""
import sys
from memorygene import Candidate, MemoryStore

NOW = "2026-10-24T10:00:00+00:00"
def c(v="A", **kw):
    f = dict(namespace="demo", subject="u", topic="t", value=v, source="fiction",
             at="2026-10-01T00:00:00+00:00")
    f.update(kw); return Candidate(**f)

s = MemoryStore()
s.ingest(c("玫瑰"), "1", now=NOW)
s.ingest(c("栀子花", intent="change", at="2026-10-10T00:00:00+00:00"), "2", now=NOW)
print("healthy current:", s.current("demo","u","t",now=NOW)["candidate"]["value"], "(id=2)")
s.db.execute("UPDATE heads SET event_id='1'")       # roll head back to older confirmed event
print("after head rollback, current:", s.current("demo","u","t",now=NOW)["candidate"]["value"], "(old value resurrected)")
report = s.verify()
print("verify() ->", {"ok": report["ok"], "problems": report["problems"]})
assert report["ok"] is True, "unexpected: verify detected rollback"
s.close()

s = MemoryStore(); s.ingest(c("A"), "1", now=NOW)
s.db.execute("DELETE FROM heads")
print("after deleting heads row, current:", s.current("demo","u","t",now=NOW))
report = s.verify()
print("verify() ->", {"ok": report["ok"], "problems": report["problems"]})
assert report["ok"] is True, "unexpected: verify detected missing head"
s.close()
print("REPRODUCED: docs say verify finds route/heads metadata anomalies, but it misses head rollback/missing head")
