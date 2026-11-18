#!/usr/bin/env python3
"""Install (or remove) the MemoryGene skill for DeepSeek Harness (DSH).

DSH discovers filesystem skills from, in priority order:

  100  <projectRoot>/.dsh/skills        (project install; projectRoot = nearest .git ancestor, else cwd)
  200  <projectRoot>/.agents/skills
  300  customSkillDirs
  400  $DSH_HOME/skills                 (user install; $DSH_HOME defaults to ~/.dsh)
  500  ~/.agents/skills

This installer only writes skill files, an adapter config and (optionally) an
empty database directory. It never edits the DSH profile, bundles, credentials
or the running application, and it never modifies a global memory system.

Examples:
  python scripts/install_dsh_skill.py                     # project install
  python scripts/install_dsh_skill.py --check
  python scripts/install_dsh_skill.py --target user       # any-workspace install
  python scripts/install_dsh_skill.py --uninstall         # restore pre-install state
"""

import argparse
import base64
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT / "skills" / "memorygene" / "SKILL.md"
MANIFEST_NAME = ".memorygene-install.json"
NAME = "memorygene"
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def dsh_home(explicit=None):
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("DSH_HOME")
    return Path(env).expanduser() if env else Path.home() / ".dsh"


def default_adapter():
    return PROJECT / ".venv" / "bin" / "memorygene-dsh"


def default_python():
    return PROJECT / ".venv" / "bin" / "python"


def resolve_target(args):
    if args.target == "user":
        root = dsh_home(args.dsh_home) / "skills"
        config = Path.home() / ".memorygene" / "dsh.json"
    else:
        root = PROJECT / ".dsh" / "skills"
        config = PROJECT / ".memorygene" / "dsh.json"
    if args.config:
        config = Path(args.config).expanduser()
    return root, config


def render_skill(values):
    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    leftovers = PLACEHOLDER.findall(text)
    if leftovers:
        raise ValueError(f"Unreplaced template placeholders: {sorted(set(leftovers))}")
    return text


def frontmatter(text):
    if not text.startswith("---\n"):
        raise ValueError("Skill file must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("Unterminated YAML frontmatter")
    fields = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def check(args):
    root, config_path = resolve_target(args)
    adapter = Path(args.adapter).expanduser() if args.adapter else default_adapter()
    python = Path(args.python).expanduser() if args.python else default_python()
    skill_file = root / NAME / "SKILL.md"
    report = {
        "ok": False,
        "project": str(PROJECT),
        "target": args.target,
        "skill_root": str(root),
        "skill_file": str(skill_file),
        "config": str(config_path),
        "adapter": str(adapter),
        "python": str(python),
        "checks": {},
        "warnings": [],
    }
    checks = report["checks"]
    checks["template_present"] = TEMPLATE.is_file()
    checks["adapter_present"] = adapter.is_file() and os.access(adapter, os.X_OK)
    checks["python_present"] = python.is_file()
    checks["skill_installed"] = skill_file.is_file()
    if skill_file.is_file():
        try:
            fields = frontmatter(skill_file.read_text(encoding="utf-8"))
            checks["frontmatter_valid"] = fields.get("name") == NAME and bool(
                fields.get("description")
            )
            checks["frontmatter"] = fields
        except ValueError as exc:
            checks["frontmatter_valid"] = False
            checks["frontmatter_error"] = str(exc)
    checks["config_present"] = config_path.is_file()
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            checks["config_valid"] = bool(config.get("db"))
            report["config_data"] = config
        except json.JSONDecodeError as exc:
            checks["config_valid"] = False
            checks["config_error"] = str(exc)
    if args.target == "project":
        checks["project_root_marker"] = (PROJECT / ".git").exists()
        if not checks["project_root_marker"]:
            report["warnings"].append(
                "Project is not a git repository: DSH falls back to the session cwd as "
                "project root, so a project install is only discovered when the session's "
                "working directory is (or is inside) the project."
            )
    if args.target == "user":
        report["warnings"].append(
            "User-level install (rank 400): discovered in every workspace. This is a "
            "user-scope install, not project integration. Use --uninstall to remove it."
        )
    report["ok"] = all(
        checks.get(key, False)
        for key in (
            "template_present",
            "adapter_present",
            "python_present",
            "skill_installed",
            "frontmatter_valid",
            "config_present",
            "config_valid",
        )
    )
    report["discovery_roots"] = {
        "project": str(PROJECT / ".dsh" / "skills"),
        "user": str(dsh_home(args.dsh_home) / "skills"),
    }
    return report


def snapshot(path):
    """Record exact bytes and permissions; never follow installation symlinks."""
    if path.is_symlink():
        raise ValueError(f"Refusing a symlink installation path: {path}")
    if not path.exists():
        return {"exists": False}
    if not path.is_file():
        raise ValueError(f"Expected a regular file: {path}")
    return {
        "exists": True,
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        "mode": stat.S_IMODE(path.stat().st_mode),
    }


def restore(path, state):
    if state["exists"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(state["data"], validate=True))
        path.chmod(state["mode"])
    elif path.exists():
        path.unlink()


def fingerprint(state):
    return (
        hashlib.sha256(base64.b64decode(state["data"])).hexdigest()
        if state["exists"]
        else None
    )


def managed_records(manifest, paths):
    records = manifest.get("files", [])
    if {item["path"] for item in records} != {str(path) for path in paths} or len(
        records
    ) != len(paths):
        raise ValueError("Install manifest paths do not match this target/config")
    # Preflight every file before touching any of them. Later user changes win.
    for item in records:
        state = snapshot(Path(item["path"]))
        if (
            fingerprint(state) != item["installed_sha256"]
            or state.get("mode") != item["installed_mode"]
        ):
            raise ValueError(
                f"Installed file was edited; preserve/reconcile it before reinstall/uninstall: {item['path']}"
            )
        original = item["original"]
        if original["exists"]:
            base64.b64decode(original["data"], validate=True)
            if type(original["mode"]) is not int:
                raise ValueError("Invalid saved file mode")
    return records


def install(args):
    root, config_path = resolve_target(args)
    adapter = Path(args.adapter).expanduser() if args.adapter else default_adapter()
    python = Path(args.python).expanduser() if args.python else default_python()
    db = Path(args.db).expanduser() if args.db else PROJECT / "var" / "memorygene.db"
    if not adapter.is_file():
        raise SystemExit(
            f"Adapter not found: {adapter}\n"
            "Install the package into the project venv first:\n"
            f"  {python} -m pip install -e {PROJECT}"
        )
    values = {
        "MG_ROOT": PROJECT,
        "MG_ADAPTER": adapter,
        "MG_PYTHON": python,
        "MG_DB": db,
        "MG_NAMESPACE": args.namespace,
        "MG_SUBJECT": args.subject,
        "MG_CONFIG": config_path,
    }
    skill_dir = root / NAME
    skill_file = skill_dir / "SKILL.md"
    manifest_path = skill_dir / MANIFEST_NAME
    paths = [skill_file, config_path]
    before = {str(path): snapshot(path) for path in paths}
    old_manifest_state = snapshot(manifest_path)
    old_manifest = (
        json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    )
    prior_records = None
    if old_manifest.get("schema") == 2:
        prior_records = managed_records(old_manifest, paths)
    config = {
        "db": str(db),
        "namespace": args.namespace,
        "subject": args.subject,
        "adapter": str(adapter),
        "python": str(python),
        "installed_by": "memorygene/scripts/install_dsh_skill.py",
        "installed_at": utc_now(),
        "target": args.target,
    }
    contents = {
        str(skill_file): render_skill(values).encode("utf-8"),
        str(config_path): (
            json.dumps(config, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
    }
    originals = (
        {item["path"]: item["original"] for item in prior_records}
        if prior_records
        else before
    )
    manifest = {
        "schema": 2,
        "name": NAME,
        "target": args.target,
        "skill_root": str(root),
        "skill_file": str(skill_file),
        "config": str(config_path),
        "db": str(db),
        "adapter": str(adapter),
        "python": str(python),
        "namespace": args.namespace,
        "subject": args.subject,
        "installed_at": utc_now(),
        "previous_manifest": old_manifest.get("previous_manifest", old_manifest_state)
        if prior_records
        else old_manifest_state,
        "rollback_baseline": old_manifest.get(
            "rollback_baseline",
            "pre-upgrade" if old_manifest_state["exists"] else "pre-install",
        ),
        "files": [
            {
                "path": str(path),
                "original": originals[str(path)],
                "installed_sha256": hashlib.sha256(contents[str(path)]).hexdigest(),
                "installed_mode": 0o600,
            }
            for path in paths
        ],
        "note": "Uninstall restores the first snapshot. Pre-legacy-install state is unavailable. Database is kept by default.",
    }
    # Write the recovery record before replacing files. Roll back on I/O failure.
    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.touch(mode=0o600, exist_ok=True)
        manifest_path.chmod(0o600)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        for path in paths:
            path.touch(mode=0o600, exist_ok=True)
            path.chmod(0o600)
            path.write_bytes(contents[str(path)])
    except OSError:
        for path in paths:
            restore(path, before[str(path)])
        restore(manifest_path, old_manifest_state)
        raise
    result = check(args)
    result["installed"] = {
        "skill_file": str(skill_file),
        "config": str(config_path),
        "db": str(db),
        "db_exists": db.is_file(),
        "manifest": str(skill_dir / MANIFEST_NAME),
    }
    result["next_steps"] = [
        "Run the adapter doctor: " + str(adapter) + " doctor",
        "Open a DSH session with working directory "
        + str(PROJECT)
        + " (project install) so the project skill root is scanned.",
        "Ask the model to use the memorygene skill explicitly; the skill is NOT an automatic per-turn integration.",
    ]
    return result


def uninstall(args):
    root, config_path = resolve_target(args)
    skill_dir = root / NAME
    manifest_path = skill_dir / MANIFEST_NAME
    snapshot(manifest_path)
    if not manifest_path.is_file():
        raise ValueError("No recovery manifest; existing files left untouched")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != 2:
        raise ValueError(
            "Legacy install has no reliable backup. Reinstall once to snapshot the current state before uninstalling"
        )
    records = managed_records(manifest, [skill_dir / "SKILL.md", config_path])
    previous = manifest["previous_manifest"]
    if previous["exists"]:
        base64.b64decode(previous["data"], validate=True)
    removed, restored = [], []
    before = {item["path"]: snapshot(Path(item["path"])) for item in records}
    manifest_before = snapshot(manifest_path)
    try:
        for item in records:
            path = Path(item["path"])
            restore(path, item["original"])
            (restored if item["original"]["exists"] else removed).append(str(path))
        restore(manifest_path, previous)
    except OSError:
        for path, state in before.items():
            restore(Path(path), state)
        restore(manifest_path, manifest_before)
        raise
    for directory in (skill_dir, config_path.parent):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    warnings = []
    if manifest["rollback_baseline"] == "pre-upgrade":
        warnings.append(
            "Restored pre-upgrade installation; the legacy installer did not retain pre-first-install backups."
        )
    if getattr(args, "purge_db", False):
        db = Path(manifest["db"])
        # Only this explicit flag requests deletion; normal rollback never touches data.
        if db.is_file():
            db.unlink()
            removed.append(str(db))
    else:
        warnings.append("Database kept.")
    return {
        "ok": True,
        "removed": removed,
        "restored": restored,
        "warnings": warnings,
        "target": args.target,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", choices=["project", "user"], default="project")
    p.add_argument(
        "--dsh-home", default=None, help="DSH_HOME override for user install"
    )
    p.add_argument("--config", default=None, help="adapter config path override")
    p.add_argument("--db", default=None, help="database path written to the config")
    p.add_argument("--adapter", default=None, help="memorygene-dsh executable path")
    p.add_argument("--python", default=None, help="project Python path")
    p.add_argument("--namespace", default="dsh")
    p.add_argument("--subject", default="owner")
    p.add_argument("--check", action="store_true", help="verify only, change nothing")
    p.add_argument("--uninstall", action="store_true", help="remove installed files")
    p.add_argument(
        "--purge-db", action="store_true", help="with --uninstall: delete the DB"
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)
    try:
        if args.check:
            result = check(args)
        elif args.uninstall:
            result = uninstall(args)
        else:
            result = install(args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
