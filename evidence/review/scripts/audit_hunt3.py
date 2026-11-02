"""Concurrency, config guard, repair matrix, routing isolation (baseline 4bb7306)."""
import concurrent.futures, json, os, sqlite3, tempfile
from pathlib import Path
from memorygene import Candidate, MemoryStore
import memorygene
from memorygene.codec import IntegrityError
print("module:", memorygene.__file__)
NOW = "2026-10-24T10:00:00+00:00"

def cand(value="A", **kw):
    f = dict(namespace="demo", subject="u", topic="t", value=value, source="fiction",
             at="2026-10-01T00:00:00+00:00")
    f.update(kw); return Candidate(**f)

print("\n=== A. 8 threads, same route, distinct values, separate connections ===")
with tempfile.TemporaryDirectory() as d:
    p = str(Path(d)/"m.db")
    with MemoryStore(p):
        pass
    def w(i):
        with MemoryStore(p) as s:
            return s.ingest(cand(f"v{i}"), f"e{i}", now=NOW)["status"]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        st = list(pool.map(w, range(8)))
    print(" statuses:", sorted(st), "| one confirmed?", st.count("confirmed") == 1)
    with MemoryStore(p) as s:
        print(" current:", s.current("demo","u","t",now=NOW)["candidate"]["value"])
        print(" history count:", len(s.history("demo","u","t",now=NOW)))

print("\n=== B. 8 threads, same route, SAME value ===")
with tempfile.TemporaryDirectory() as d:
    p = str(Path(d)/"m.db")
    with MemoryStore(p): pass
    def w2(i):
        with MemoryStore(p) as s:
            return s.ingest(cand("same"), f"e{i}", now=NOW)["status"]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        st = list(pool.map(w2, range(8)))
    print(" statuses:", sorted(st), "| confirmed:", st.count("confirmed"), "duplicate:", st.count("duplicate"))

print("\n=== C. 8 threads, SAME event_id/content (write race) ===")
with tempfile.TemporaryDirectory() as d:
    p = str(Path(d)/"m.db")
    with MemoryStore(p): pass
    def w3(i):
        with MemoryStore(p) as s:
            return s.ingest(cand("x"), "same-id", now=NOW)["id"]
    errs = []
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        futs = [pool.submit(w3, i) for i in range(8)]
        for f in futs:
            try: f.result()
            except Exception as e: errs.append(type(e).__name__+": "+str(e))
    with MemoryStore(p) as s:
        n = s.db.execute("SELECT count(*) FROM events").fetchone()[0]
    print(" errors:", errs, "| events stored:", n)

print("\n=== D. config guard matrix ===")
with tempfile.TemporaryDirectory() as d:
    p = str(Path(d)/"m.db")
    with MemoryStore(p, index="plain", protection="copy") as s:
        s.ingest(cand(), "1", now=NOW)
    for kw in (dict(index="complement"), dict(protection="complement"), dict(protection="none")):
        try:
            MemoryStore(p, **kw); print(" OPENED despite", kw, "<-- BAD")
        except ValueError as e:
            print(" rejected", kw, "->", e)
    # mutate config key
    db = sqlite3.connect(p); db.execute("UPDATE config SET value='2' WHERE key='schema'"); db.commit(); db.close()
    try:
        MemoryStore(p); print(" OPENED despite schema=2 <-- BAD")
    except ValueError as e:
        print(" rejected schema=2 ->", e)
    db = sqlite3.connect(p); db.execute("UPDATE config SET value='1' WHERE key='schema'"); db.execute("INSERT INTO config VALUES('extra','x')"); db.commit(); db.close()
    try:
        MemoryStore(p); print(" OPENED despite extra config key <-- BAD")
    except ValueError as e:
        print(" rejected extra config key ->", e)
    # empty config on nonempty db
    db = sqlite3.connect(p); db.execute("DELETE FROM config"); db.commit(); db.close()
    try:
        MemoryStore(p); print(" OPENED despite missing config <-- BAD")
    except ValueError as e:
        print(" rejected missing config ->", e)

print("\n=== E. repair matrix (protection modes) ===")
for mode in ("none","copy","complement"):
    with MemoryStore(protection=mode) as s:
        s.ingest(cand(), "1", now=NOW)
        s.db.execute("UPDATE events SET payload=x'00'")
        try:
            s.repair("1"); print(f" {mode}: repaired")
        except IntegrityError as e:
            print(f" {mode}: repair refused -> {e}")
        # now corrupt both
        s.db.execute("UPDATE events SET payload=x'00', backup=x'00'")
        try:
            s.repair("1"); print(f" {mode}: repaired BOTH-lost <-- BAD")
        except IntegrityError as e:
            print(f" {mode}: both-lost refused -> {e}")
        # forget works even when corrupt
        try:
            print(f" {mode}: forget count:", s.forget("demo","u","t"))
        except Exception as e:
            print(f" {mode}: forget failed:", type(e).__name__, e)

print("\n=== F. repair keeps heads / never resurrects ===")
s = MemoryStore()
s.ingest(cand("A"), "1", now=NOW)
s.ingest(cand("B", intent="change", at="2026-10-02T00:00:00Z"), "2", now=NOW)
s.db.execute("UPDATE events SET payload=x'00' WHERE id IN ('1','2')")
s.repair("1"); s.repair("2")
print(" current after repairing both:", s.current("demo","u","t",now=NOW)["candidate"]["value"], "| head id:", s.current("demo","u","t",now=NOW)["id"])
# corrupt then repair the OLD event; head must stay B
s.close()

print("\n=== G. routing collision probes ===")
s = MemoryStore()
pairs = [
    (("a.b","c","d"), ("a","b.c","d")),
    (("a","b","c","persistent",""), ("a","b","c","session","")),
    (("a","b","c","session","x"), ("a","b","c","session"," y")),
    (('x"y',"s","t"), ('x\\"y',"s","t")),
    (("é","s","t"), ("e\u0301","s","t")),
]
for a,b in pairs:
    ra, rb = s._route(*a), s._route(*b)
    print(f"  {a} vs {b} -> {'SAME (collision)' if ra==rb else 'distinct'}")
# structure-level collision impossible? try injecting json-ish separators via fields
print("  route example bytes len:", len(s._route("demo","u","t")))
s.close()
