"""Wrong-path / foreign-SQLite adoption + fuzz invariants (baseline 4bb7306)."""
import json, random, sqlite3, tempfile
from pathlib import Path
from memorygene import Candidate, MemoryStore
import memorygene
from memorygene.codec import IntegrityError, checksum
print("module:", memorygene.__file__)
NOW = "2026-10-24T10:00:00+00:00"

def cand(value="A", **kw):
    f = dict(namespace="demo", subject="u", topic="t", value=value, source="fiction",
             at="2026-10-01T00:00:00+00:00")
    f.update(kw); return Candidate(**f)

print("\n=== A. MemoryStore(opened on a FOREIGN sqlite database) ===")
with tempfile.TemporaryDirectory() as d:
    p = str(Path(d)/"other_app.db")
    outer = sqlite3.connect(p)
    outer.execute("CREATE TABLE invoices(id INTEGER PRIMARY KEY, amount REAL)")
    outer.execute("INSERT INTO invoices(amount) VALUES (42.5)")
    outer.commit(); outer.close()
    before = sqlite3.connect(p); before_tables = [r[0] for r in before.execute("SELECT name FROM sqlite_master WHERE type='table'")]; before.close()
    print(" before tables:", before_tables)
    s = MemoryStore(p)   # silently adopts the foreign database
    s.ingest(cand(), "1", now=NOW)
    s.close()
    after = sqlite3.connect(p)
    after_tables = [r[0] for r in after.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    cfg = dict(after.execute("SELECT key,value FROM config"))
    print(" after  tables:", after_tables)
    print(" injected config:", cfg)
    print(" foreign row intact:", after.execute("SELECT amount FROM invoices").fetchone())
    after.close()

print("\n=== A2. non-empty SQLite DB without MemoryGene tables -> adopted (no marker check) ===")
with tempfile.TemporaryDirectory() as d:
    p = str(Path(d)/"x.db")
    db = sqlite3.connect(p); db.execute("CREATE TABLE foo(x)"); db.execute("INSERT INTO foo VALUES(1)"); db.commit(); db.close()
    try:
        with MemoryStore(p) as s:
            print(" adopted foreign DB silently; current:", s.current("demo","u","t",now=NOW))
    except Exception as e:
        print(" rejected:", type(e).__name__, e)

print("\n=== B. fuzz: plain vs complement policy equivalence (500 steps, wide field space) ===")
rng = random.Random(20261024)
values = ["A","B","C","D","caf\u00e9","cafe\u0301","", "玫瑰"]
statuses = ["explicit","uncertain","inferred"]
ints = ["assert","change","correct","supplement"]
div = []
plain = MemoryStore(index="plain"); dna = MemoryStore(index="complement")
event_states = {}
for step in range(500):
    kw = dict(certainty=rng.choice(statuses), intent=rng.choice(ints),
              importance=rng.choice([0.2,0.5,0.7,0.99,1]),
              scope=rng.choice(["persistent","session"]))
    if kw["scope"] == "session": kw["session"] = rng.choice(["s1","s2"])
    if rng.random() < 0.2: kw["expires_at"] = rng.choice(["2026-10-02T00:00:00Z","2026-10-30T00:00:00Z"])
    if rng.random() < 0.1: kw["sensitive"] = True; kw["consent"] = rng.choice([True,False])
    at = rng.choice(["2026-09-01T00:00:00Z","2026-10-01T00:00:00Z","2026-10-10T00:00:00Z","2026-10-20T00:00:00Z"])
    c = cand(rng.choice(values), at=at, **kw)
    eid = f"e{step}"
    resolves = None
    if rng.random() < 0.3 and event_states:
        resolves = rng.choice(list(event_states))
    try:
        ra = plain.ingest(c, eid, now=NOW, resolves=resolves)
        ea = None
    except Exception as e:
        ra = None; ea = (type(e).__name__, str(e))
    try:
        rb = dna.ingest(c, eid, now=NOW, resolves=resolves)
        eb = None
    except Exception as e:
        rb = None; eb = (type(e).__name__, str(e))
    if ra != rb or ea != eb:
        div.append((step, eid, ra, rb, ea, eb)); 
        if len(div) <= 3: print(" DIVERGENCE at", step, "->", ra, rb, ea, eb)
    if ra: event_states[eid] = ra["status"]
print(" divergences:", len(div), "of 500 steps")
plain.close(); dna.close()

print("\n=== C. fuzz invariants (500 steps, one store) ===")
rng = random.Random(7)
s = MemoryStore()
ids = []
violations = []
for step in range(500):
    kw = dict(certainty=rng.choice(statuses), intent=rng.choice(ints),
              importance=rng.choice([0.2,0.5,0.7,0.99]),
              scope=rng.choice(["persistent","session"]))
    if kw["scope"] == "session": kw["session"] = rng.choice(["s1","s2"])
    at = rng.choice(["2026-09-01T00:00:00Z","2026-10-01T00:00:00Z","2026-10-10T00:00:00Z"])
    if rng.random() < 0.15: kw["expires_at"] = rng.choice(["2026-10-02T00:00:00Z","2026-10-30T00:00:00Z"])
    c = cand(rng.choice(values), at=at, **kw)
    eid = f"e{step}"
    try:
        r = s.ingest(c, eid, now=NOW)
    except ValueError:
        continue
    ids.append(eid)
    if r.get("status") == "confirmed":
        head = s._head(s._route("demo","u","t",c.scope,c.session))
        # note: subject may differ? all subjects "u" here
        if head is None or head["id"] != eid:
            # could be confirmed but another confirmed after? no, immediate check
            violations.append(("confirmed_not_head", eid, head["id"] if head else None))
    for scope, session in (("persistent",""),("session","s1"),("session","s2")):
        cur = s.current("demo","u","t",scope=scope,session=session,now=NOW)
        if cur is not None:
            if cur["status"] != "confirmed":
                violations.append(("current_not_confirmed", eid, cur["status"]))
            headrow = s.db.execute("SELECT s.* FROM heads h JOIN events e ON e.id=h.event_id JOIN events s ON s.id=h.event_id WHERE h.route=?",(s._route("demo","u","t",scope,session),)).fetchone()
            if headrow is None:
                violations.append(("current_without_head", eid))
        hist = s.history("demo","u","t",scope=scope,session=session,now=NOW)
        hist_ids = [e["id"] for e in hist]
        stored = [r["id"] for r in s.db.execute("SELECT id FROM events WHERE route=? ORDER BY seq",(s._route("demo","u","t",scope,session),))]
        if hist_ids != [x for x in stored if x in set(hist_ids)] and set(hist_ids) != set(stored):
            violations.append(("history_mismatch", eid, scope, session, hist_ids, stored))
print(" invariant violations:", violations[:5], "| total:", len(violations))

print("\n=== D. fuzz random corruption: never returns wrong bytes silently ===")
rng = random.Random(11)
bad = 0; ok = 0
for trial in range(300):
    data = bytes(rng.randrange(256) for _ in range(rng.randrange(1,120)))
    mode = rng.choice(["none","copy","complement"])
    expected = checksum(data)
    backup = None if mode=="none" else (data if mode=="copy" else bytes(b^255 for b in data))
    primary = bytearray(data)
    site = rng.choice(["primary","backup","digest","none"])
    if site in ("primary","none") and primary and rng.random()<0.8:
        primary[rng.randrange(len(primary))] ^= 1 << rng.randrange(8)
    backup2 = backup
    if site=="backup" and backup is not None:
        bb = bytearray(backup); bb[rng.randrange(len(bb))] ^= 1 << rng.randrange(8); backup2 = bytes(bb)
    if site=="digest":
        expected = "f"*64
    from memorygene.codec import recover
    try:
        out = recover(bytes(primary), backup2, expected, mode)
        if out != data: bad += 1
        else: ok += 1
    except IntegrityError:
        ok += 1
print(" corruption fuzz: wrong-bytes returns:", bad, "| accepted-or-refused correctly:", ok)
