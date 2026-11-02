"""Project adapter that connects a chat host (DeepSeek Harness) to the core.

The adapter deliberately does only mechanical work: it resolves a *fixed*
database and identity, validates and fills in timestamps, builds a
``Candidate`` from explicit fields, and calls :class:`MemoryStore`. Natural
language extraction stays with the calling agent; this module never invents a
value, consent, evidence or timestamp, and it never silently creates a new
database when the expected one is missing.

Run ``memorygene-dsh doctor`` first: it prints the resolved database path,
identity, session and database configuration without creating anything.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, tasks
from .core import Candidate, MemoryStore, canonical
from .recall import recall
from .reconsolidate import advise, locate, review

TOPIC_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
MAX_TOPIC_CHARS = 120
MAX_VALUE_CHARS = 2000
MAX_SOURCE_CHARS = 4000
MAX_EVENT_ID_CHARS = 160
CONFIG_RELATIVE = Path(".memorygene") / "dsh.json"
USER_CONFIG = Path.home() / ".memorygene" / "dsh.json"
DEFAULT_NAMESPACE = "dsh"
DEFAULT_SUBJECT = "owner"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_config(explicit=None):
    """Resolve the adapter configuration file, or ``None``.

    Explicit flag and ``MEMORYGENE_CONFIG`` win, then a ``.memorygene/dsh.json``
    found by walking up from the current directory, then the user-level config.
    Missing configuration is an error later, never a silent new database.
    """
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("MEMORYGENE_CONFIG")
    if env:
        return Path(env).expanduser()
    here = Path.cwd().resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_RELATIVE
        if candidate.is_file():
            return candidate
    if USER_CONFIG.is_file():
        return USER_CONFIG
    return None


def resolve_settings(args):
    config_path = find_config(getattr(args, "config", None))
    config = {}
    if config_path is not None:
        if not config_path.is_file():
            raise ValueError(f"Configuration file not found: {config_path}")
        config = _read_json(config_path)
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a JSON object")
    db = getattr(args, "db", None) or os.environ.get("MEMORYGENE_DB") or config.get("db")
    if not db:
        raise ValueError(
            "No MemoryGene database configured. Pass --db, set MEMORYGENE_DB, "
            "or install the skill with scripts/install_dsh_skill.py. "
            "Refusing to create an accidental new database."
        )
    namespace = (
        getattr(args, "namespace", None)
        or os.environ.get("MEMORYGENE_NAMESPACE")
        or config.get("namespace")
        or DEFAULT_NAMESPACE
    )
    subject = (
        getattr(args, "subject", None)
        or os.environ.get("MEMORYGENE_SUBJECT")
        or config.get("subject")
        or DEFAULT_SUBJECT
    )
    for label, value in (("namespace", namespace), ("subject", subject)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be nonempty text")
    update_policy = config.get("update_policy", "confirm")
    if update_policy not in {"confirm", "latest"}:
        raise ValueError("update_policy in the configuration must be confirm or latest")
    return {
        "db": str(Path(db).expanduser()),
        "namespace": namespace,
        "subject": subject,
        "config": str(config_path) if config_path else None,
        "env_session": os.environ.get("DSH_SESSION_ID", ""),
        "update_policy": update_policy,
    }


def resolve_session(args, settings):
    value = (
        getattr(args, "session", None)
        or os.environ.get("MEMORYGENE_SESSION")
        or settings["env_session"]
    )
    return value.strip() if isinstance(value, str) else ""


def open_store(settings, allow_create):
    path = settings["db"]
    created = False
    if path != ":memory:" and not Path(path).is_file():
        if not allow_create:
            raise ValueError(
                f"MemoryGene database not found at {path}. Refusing to create a new "
                "database implicitly; pass --allow-create only when a new store is "
                "intended, or fix the configured path."
            )
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        created = True
    store = MemoryStore(path)
    if created:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return store


def check_topic(topic):
    if not isinstance(topic, str) or not TOPIC_PATTERN.fullmatch(topic):
        raise ValueError(
            "topic must be a stable dotted canonical name, e.g. "
            "preference.favorite_flower (lowercase ascii letters, digits, '.', '-', '_')"
        )
    return topic


def payload(**fields):
    out = {"ok": True, "version": __version__, **fields}
    return out


def emit(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def cmd_doctor(args, settings):
    db = settings["db"]
    report = {
        "version": __version__,
        "python": sys.executable,
        "db": db,
        "db_configured": db != ":memory:",
        "db_exists": db == ":memory:" or Path(db).is_file(),
        "config": settings["config"],
        "namespace": settings["namespace"],
        "subject": settings["subject"],
        "session_env": settings["env_session"] or None,
        "update_policy": settings["update_policy"],
        "cwd": str(Path.cwd()),
        "environment_overrides": {
            "MEMORYGENE_DB": os.environ.get("MEMORYGENE_DB"),
            "MEMORYGENE_CONFIG": os.environ.get("MEMORYGENE_CONFIG"),
            "MEMORYGENE_NAMESPACE": os.environ.get("MEMORYGENE_NAMESPACE"),
            "MEMORYGENE_SUBJECT": os.environ.get("MEMORYGENE_SUBJECT"),
        },
        "ready": False,
        "db_config": None,
        "db_error": None,
        "subjects_hint": "The adapter refuses to create a missing database unless --allow-create is passed.",
    }
    if report["db_exists"] and db != ":memory:":
        try:
            with MemoryStore(db) as store:
                report["db_config"] = dict(
                    store.db.execute("SELECT key,value FROM config")
                )
                report["ready"] = True
        except (ValueError, sqlite3.Error) as exc:
            report["db_error"] = str(exc)
    return payload(**report)


def cmd_remember(args, settings):
    check_topic(args.topic)
    now = args.now or utc_now()
    session = resolve_session(args, settings)
    if args.scope == "session" and not session:
        raise ValueError(
            "Session-scoped memory requires a session ID (--session or DSH_SESSION_ID); "
            "persistent memory is the default."
        )
    if args.scope == "persistent" and session and args.session:
        raise ValueError("Persistent scope must not carry a session ID")
    sensitive = bool(args.sensitive)
    consent = bool(args.consent)
    if consent and not sensitive:
        raise ValueError("--consent is only meaningful together with --sensitive")
    consent_evidence = (args.consent_evidence or "").strip()
    if sensitive and consent and not consent_evidence:
        raise ValueError(
            "Sensitive memory needs verbatim --consent-evidence from the user; "
            "a boolean alone is not evidence of consent."
        )
    source = args.source.strip()
    if not source:
        raise ValueError("source must be the user's minimal verbatim evidence")
    value = unicodedata.normalize("NFC", args.value).strip()
    if not value:
        raise ValueError("value must be nonempty text")
    if len(args.topic) > MAX_TOPIC_CHARS:
        raise ValueError(f"topic exceeds {MAX_TOPIC_CHARS} characters")
    if len(value) > MAX_VALUE_CHARS:
        raise ValueError(f"value exceeds {MAX_VALUE_CHARS} characters")
    if len(source) > MAX_SOURCE_CHARS:
        raise ValueError(f"source exceeds {MAX_SOURCE_CHARS} characters")
    if len(consent_evidence) > MAX_SOURCE_CHARS:
        raise ValueError(f"consent evidence exceeds {MAX_SOURCE_CHARS} characters")
    if sensitive and consent:
        source = f"{source}【用户同意原话：{consent_evidence}】"
    candidate = Candidate(
        namespace=settings["namespace"],
        subject=settings["subject"],
        topic=args.topic,
        value=value,
        source=source,
        at=args.at or now,
        certainty=args.certainty,
        intent=args.intent,
        importance=args.importance,
        scope=args.scope,
        session=session if args.scope == "session" else "",
        expires_at=args.expires_at,
        sensitive=sensitive,
        consent=consent,
    )
    event_id = args.event_id or f"dsh-{now.replace(':', '').replace('+', '')}-{uuid.uuid4().hex[:8]}"
    if len(event_id) > MAX_EVENT_ID_CHARS:
        raise ValueError(f"event_id exceeds {MAX_EVENT_ID_CHARS} characters")
    with open_store(settings, args.allow_create) as store:
        result = store.ingest(
            candidate, event_id, now=now, resolves=args.resolves,
            update=args.update or settings["update_policy"],
        )
        advice = advise(store, candidate, result, now=now, visible_session=session)
    return payload(
        command="remember",
        db=settings["db"],
        namespace=settings["namespace"],
        subject=settings["subject"],
        event_id=event_id,
        result=result,
        advice=advice,
    )


def _query_args(args, settings):
    check_topic(args.topic)
    fields = dict(
        namespace=settings["namespace"],
        subject=settings["subject"],
        topic=args.topic,
        scope=args.scope,
        session=resolve_session(args, settings) if args.scope == "session" else "",
    )
    if args.now:
        fields["now"] = args.now
    return fields


def cmd_current(args, settings):
    with open_store(settings, args.allow_create) as store:
        result = store.current(**_query_args(args, settings))
    return payload(command="current", db=settings["db"], current=result)


def cmd_history(args, settings):
    with open_store(settings, args.allow_create) as store:
        result = store.history(**_query_args(args, settings))
    return payload(command="history", db=settings["db"], history=result)


def cmd_topics(args, settings):
    with open_store(settings, args.allow_create) as store:
        result = store.topics(
            settings["namespace"], settings["subject"], now=args.now,
            visible_session=resolve_session(args, settings),
        )
    return payload(
        command="topics",
        db=settings["db"],
        namespace=settings["namespace"],
        subject=settings["subject"],
        topics=result,
    )


def cmd_recall(args, settings):
    with open_store(settings, args.allow_create) as store:
        return recall(
            store, settings["namespace"], settings["subject"], args.query,
            now=args.now, visible_session=resolve_session(args, settings),
            limit=args.limit, budget_chars=args.budget_chars,
        )


def cmd_locate(args, settings):
    check_topic(args.topic)
    with open_store(settings, args.allow_create) as store:
        related = locate(
            store, settings["namespace"], settings["subject"], args.topic,
            unicodedata.normalize("NFC", args.value), args.source or "",
            now=args.now, visible_session=resolve_session(args, settings),
            limit=args.limit,
        )
    return payload(command="locate", db=settings["db"], related=related,
                   note="lexical recognition cues; suggestions only, nothing was written")


def cmd_review(args, settings):
    with open_store(settings, args.allow_create) as store:
        result = review(
            store, settings["namespace"], settings["subject"], now=args.now,
            visible_session=resolve_session(args, settings),
        )
    return payload(db=settings["db"], **{k: v for k, v in result.items() if k != "ok"})


def cmd_forget(args, settings):
    fields = _query_args(args, settings)
    # Forget removes the entire route, including expired evidence; a test clock
    # affects reads but must not restrict deletion or reach MemoryStore.forget.
    fields.pop("now", None)
    with open_store(settings, args.allow_create) as store:
        count = store.forget(**fields)
    return payload(command="forget", db=settings["db"], forgotten=count)


def cmd_task(args, settings):
    session = resolve_session(args, settings)
    if not session:
        raise ValueError("Task checkpoints require --session or DSH_SESSION_ID")
    document = None
    if args.command == "task-save":
        # Do not echo private draft contents into tool output/errors.
        with Path(args.file).open("r", encoding="utf-8") as source:
            raw = source.read(32001)
        if len(raw) > 32000:
            raise ValueError("Task input file exceeds 32000 characters")
        document = json.loads(raw)
        tasks.validate_document(document)
    with open_store(settings, args.allow_create) as store:
        identity = (store, settings["namespace"], settings["subject"])
        if args.command == "task-resume":
            result = tasks.resume(*identity, session, args.checkpoint_id,
                                  allow_cross_session=args.allow_cross_session, now=args.now)
        elif args.command == "task-save":
            result = tasks.save(*identity, args.task, session, document,
                                previous_id=args.previous_id, expires_at=args.expires_at, now=args.now)
        elif args.command == "task-show":
            result = tasks.show(*identity, args.task, session, now=args.now)
        elif args.command == "task-forget":
            result = {"status": "forgotten", "versions": tasks.forget(*identity, args.task, session)}
        else:
            tasks.repair(*identity, args.task, session, args.checkpoint_id)
            result = {"status": "bytes_repaired", "checkpoint_id": args.checkpoint_id,
                      "note": "Source freshness is rechecked by task-show; repair never selects an older version."}
    return payload(command=args.command, result=result)


def cmd_verify(args, settings):
    with open_store(settings, args.allow_create) as store:
        result = store.verify()
    return payload(
        command="verify",
        db=settings["db"],
        integrity=result,
        note="verify is a read-only full scan; it never repairs or changes heads",
    )


def cmd_repair(args, settings):
    with open_store(settings, args.allow_create) as store:
        store.repair(args.event_id)
    return payload(
        command="repair",
        db=settings["db"],
        repaired=args.event_id,
        note="repair only restores bytes; it never changes heads or rolls back versions",
    )


GLOBAL_FLAGS = {
    "--config",
    "--db",
    "--namespace",
    "--subject",
    "--session",
    "--now",
}
GLOBAL_SWITCHES = {"--allow-create"}


def normalize_argv(argv):
    """Allow the global flags to appear before or after the subcommand.

    ``argparse`` subparsers parse into a fresh namespace, so a global flag given
    before the subcommand would be discarded. Moving global flags to the front
    keeps the documented ``--flag subcommand`` order and also accepts
    ``subcommand --flag``.
    """
    front, rest = [], []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in GLOBAL_FLAGS:
            if i + 1 >= len(argv):
                raise SystemExit(f"memorygene-dsh: {token} requires a value")
            front.extend([token, argv[i + 1]])
            i += 2
            continue
        if any(token.startswith(flag + "=") for flag in GLOBAL_FLAGS):
            front.append(token)
            i += 1
            continue
        if token in GLOBAL_SWITCHES:
            front.append(token)
            i += 1
            continue
        rest.append(token)
        i += 1
    return front + rest


def build_parser():
    p = argparse.ArgumentParser(
        prog="memorygene-dsh",
        description="MemoryGene adapter for DeepSeek Harness chats",
    )
    p.add_argument("--config", default=None, help="adapter config JSON path")
    p.add_argument("--db", default=None, help="database path override")
    p.add_argument("--namespace", default=None, help="logical namespace")
    p.add_argument("--subject", default=None, help="memory subject (user)")
    p.add_argument("--session", default=None, help="session id (session scope)")
    p.add_argument(
        "--now",
        default=None,
        help="testing-only clock override (timezone-aware ISO text)",
    )
    p.add_argument(
        "--allow-create",
        action="store_true",
        default=False,
        help="explicitly allow creating a missing database file",
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="show resolved paths/identity")
    remember = sub.add_parser(
        "remember", help="store one extracted candidate"
    )
    remember.add_argument("--topic", required=True)
    remember.add_argument("--value", required=True)
    remember.add_argument("--source", required=True, help="minimal verbatim evidence")
    remember.add_argument("--at", default=None, help="evidence time (ISO, tz-aware)")
    remember.add_argument(
        "--certainty", choices=["explicit", "uncertain", "inferred"], default="explicit"
    )
    remember.add_argument(
        "--intent",
        choices=["assert", "change", "correct", "supplement"],
        default="assert",
    )
    remember.add_argument("--importance", type=float, default=0.7)
    remember.add_argument(
        "--scope", choices=["persistent", "session"], default="persistent"
    )
    remember.add_argument("--expires-at", default=None)
    remember.add_argument("--sensitive", action="store_true")
    remember.add_argument("--consent", action="store_true")
    remember.add_argument("--consent-evidence", default=None)
    remember.add_argument("--resolves", default=None)
    remember.add_argument("--event-id", default=None)
    remember.add_argument(
        "--update", choices=["confirm", "latest"], default=None,
        help="how a newer unmarked assertion is handled (default from config, else confirm)",
    )
    for name in ("current", "history", "forget"):
        query = sub.add_parser(name)
        query.add_argument("--topic", required=True)
        query.add_argument(
            "--scope", choices=["persistent", "session"], default="persistent"
        )
    sub.add_parser("topics")
    search = sub.add_parser("recall", help="budgeted lexical discovery of current facts")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--budget-chars", type=int, default=2000)
    find = sub.add_parser("locate", help="rank existing slots that may hold the same attribute")
    find.add_argument("--topic", required=True)
    find.add_argument("--value", required=True)
    find.add_argument("--source", default="")
    find.add_argument("--limit", type=int, default=5)
    sub.add_parser("review", help="unresolved evidence and possible duplicate slots")
    sub.add_parser("verify")
    repair = sub.add_parser("repair")
    repair.add_argument("--event-id", required=True)
    task_save = sub.add_parser("task-save", help="save an explicit task checkpoint")
    task_save.add_argument("--task", required=True)
    task_save.add_argument("--file", required=True, help="structured task JSON file")
    task_save.add_argument("--previous-id", default=None)
    task_save.add_argument("--expires-at", default=None)
    for name in ("task-show", "task-forget", "task-repair"):
        task = sub.add_parser(name)
        task.add_argument("--task", required=True)
        if name == "task-repair":
            task.add_argument("--checkpoint-id", required=True)
    task_resume = sub.add_parser("task-resume", help="review a task using its exact checkpoint ID")
    task_resume.add_argument("--checkpoint-id", required=True)
    task_resume.add_argument("--allow-cross-session", action="store_true")
    return p


COMMANDS = {
    "doctor": cmd_doctor,
    "remember": cmd_remember,
    "current": cmd_current,
    "history": cmd_history,
    "topics": cmd_topics,
    "recall": cmd_recall,
    "locate": cmd_locate,
    "review": cmd_review,
    "verify": cmd_verify,
    "forget": cmd_forget,
    "repair": cmd_repair,
    **{name: cmd_task for name in (
        "task-save", "task-show", "task-resume", "task-forget", "task-repair",
    )},
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(normalize_argv(argv))
    try:
        settings = resolve_settings(args)
        result = COMMANDS[args.command](args, settings)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc), "error_type": type(exc).__name__},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    if args.command == "recall":
        print(canonical(result))
    else:
        emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
