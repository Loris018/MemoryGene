"""P1 repro: metadata (non-payload) corruption is NOT fail-closed even though
README.md says "损坏读写失败关闭" and SECURITY.md says "无法恢复时返回错误".
Only payload/digest bytes are checksum-verified."""
from memorygene import Candidate, MemoryStore

def cand(v="A"):
    return Candidate("demo","fictional-user","t",v,"fiction","2026-10-01T00:00:00Z")

NOW = "2026-10-24T10:00:00Z"

print("case 1: heads.route corrupted -> current() silently returns None")
s = MemoryStore(); s.ingest(cand(), "1", now=NOW)
s.db.execute("UPDATE heads SET route='CORRUPT'")
print("  current():", s.current("demo","fictional-user","t",now=NOW))
s.close()

print("case 2: events.route corrupted on a non-head event -> history() silently drops it")
s = MemoryStore()
s.ingest(cand(), "1", now=NOW)
s.ingest(cand("B"), "2", now=NOW) if False else None
s.ingest(Candidate("demo","fictional-user","t","B","fiction","2026-10-10T00:00:00Z",intent="change"), "2", now=NOW)
s.db.execute("UPDATE events SET route='CORRUPT' WHERE id='1'")
print("  history ids:", [e["id"] for e in s.history("demo","fictional-user","t",now=NOW)])
print("  expected: IntegrityError (README: '损坏读写失败关闭'), observed: silently missing id=1")
s.close()

print("case 3 (control): payload corruption IS fail-closed")
from memorygene.codec import IntegrityError
s = MemoryStore(); s.ingest(cand(), "1", now=NOW)
s.db.execute("UPDATE events SET payload=x'00' WHERE id='1'")
try:
    s.current("demo","fictional-user","t",now=NOW)
except IntegrityError as e:
    print("  IntegrityError:", e)
s.close()
