import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .core import Candidate, MemoryStore


def build_parser():
    p = argparse.ArgumentParser(description="MemoryGene structured local memory core")
    p.add_argument("--db", required=True)
    p.add_argument("--index", choices=["plain", "complement"], default="complement")
    p.add_argument(
        "--protection", choices=["none", "copy", "complement"], default="complement"
    )
    sub = p.add_subparsers(dest="command", required=True)
    add = sub.add_parser("ingest")
    add.add_argument("file", help="UTF-8 JSON object with event_id and candidate")
    for command in ("current", "history", "forget"):
        query = sub.add_parser(command)
        for field in ("namespace", "subject", "topic"):
            query.add_argument("--" + field, required=True)
        query.add_argument(
            "--scope", choices=["persistent", "session"], default="persistent"
        )
        query.add_argument("--session", default="")
    topics = sub.add_parser("topics")
    topics.add_argument("--namespace", required=True)
    topics.add_argument("--subject", required=True)
    sub.add_parser("verify")
    sub.add_parser("repair").add_argument("event_id")
    return p


READ_COMMANDS = {"current", "history", "topics", "forget", "repair", "verify"}


def main():
    a = build_parser().parse_args()
    try:
        if a.command in READ_COMMANDS and a.db != ":memory:" and not Path(a.db).is_file():
            raise ValueError(
                f"MemoryGene database not found at {a.db}; refusing to create a "
                "database for a read/delete command (only ingest creates a new store)"
            )
        with MemoryStore(a.db, index=a.index, protection=a.protection) as store:
            if a.command == "ingest":
                data = json.loads(Path(a.file).read_text(encoding="utf-8"))
                result = store.ingest(
                    Candidate(**data["candidate"]),
                    data["event_id"],
                    resolves=data.get("resolves"),
                )
            elif a.command == "repair":
                store.repair(a.event_id)
                result = {"repaired": a.event_id}
            elif a.command == "topics":
                result = store.topics(a.namespace, a.subject)
            elif a.command == "verify":
                result = store.verify()
            else:
                result = getattr(store, a.command)(
                    a.namespace, a.subject, a.topic, scope=a.scope, session=a.session
                )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
