"""P1 repro: CLI silently creates a brand-new store on a mistyped/missing --db path,
so `forget` on the wrong path exits 0 with `0` and a fresh DB file is created."""
import subprocess, sys, tempfile
from pathlib import Path

CAND = Path(__file__).with_name("candidate.json")
cand = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
cand.write('{"event_id":"demo-1","candidate":{"namespace":"demo","subject":"fictional-user",'
           '"topic":"preference.favorite_flower","value":"玫瑰","source":"虚构用户：我最喜欢玫瑰。",'
           '"at":"2026-10-01T00:00:00Z"}}')
cand.close()

def run(*args):
    r = subprocess.run([sys.executable, "-m", "memorygene.cli", *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

with tempfile.TemporaryDirectory() as d:
    typo = str(Path(d) / "membory.db")   # typo path: does not exist
    print("expected: refuse or at least warn; observed:")
    rc, out, err = run("--db", typo, "forget",
                       "--namespace", "demo", "--subject", "fictional-user", "--topic", "t")
    print(f"  forget on missing/typo db -> exit={rc} stdout={out!r} stderr={err!r}")
    print(f"  new db file created: {Path(typo).exists()} size={Path(typo).stat().st_size if Path(typo).exists() else 0}")
    rc, out, err = run("--db", typo, "current",
                       "--namespace", "demo", "--subject", "fictional-user", "--topic", "t")
    print(f"  current on it -> exit={rc} stdout={out!r} stderr={err!r}")
