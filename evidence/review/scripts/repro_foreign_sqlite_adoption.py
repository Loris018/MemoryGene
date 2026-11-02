"""P1 repro: MemoryStore() adopts a foreign SQLite database (non-empty, no MemoryGene
tables) and injects config/events/heads tables instead of refusing."""
import sqlite3, tempfile
from pathlib import Path
from memorygene import Candidate, MemoryStore

with tempfile.TemporaryDirectory() as d:
    p = str(Path(d) / "other_app.db")
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE invoices(id INTEGER PRIMARY KEY, amount REAL)")
    db.execute("INSERT INTO invoices(amount) VALUES (42.5)")
    db.commit(); db.close()
    with MemoryStore(p) as s:
        s.ingest(Candidate("demo","fictional-user","t","A","fiction","2026-10-01T00:00:00Z"),
                 "e1", now="2026-10-24T10:00:00Z")
    db = sqlite3.connect(p)
    tables = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    print("tables after MemoryStore():", tables)
    print("expected: refuse to manage a database without MemoryGene config marker")
    print("observed: adopted + schema injected; foreign data still present ->",
          db.execute("SELECT amount FROM invoices").fetchone())
    db.close()
