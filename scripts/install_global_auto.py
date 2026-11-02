#!/usr/bin/env python3
"""Enable/disable cross-project automatic MemoryGene usage in DeepSeek Harness.

What it does (and does not do):

* DSH loads user-global instructions from ``$DSH_HOME/AGENTS.md`` (default
  ``~/.dsh/AGENTS.md``) into every session of every workspace. This script
  writes a clearly delimited MemoryGene protocol section there, so the model is
  told to load the ``memorygene`` skill before answering personal-memory
  questions and to write explicit long-term statements afterwards.
* It also makes sure the user-level skill is installed at
  ``$DSH_HOME/skills/memorygene/`` so the skill is auto-advertised in every
  workspace. DSH has **no** project-level code-plugin / hook channel in this
  version, so this instructions file is a prompt convention, NOT an enforced
  mechanism. The model may still skip it; direct user requests always win.
* It never edits the DSH profile, plugins, credentials or managed memory.

Commands:
  python scripts/install_global_auto.py            # enable (safe, reversible)
  python scripts/install_global_auto.py --check    # verify only
  python scripts/install_global_auto.py --uninstall
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT / "tools" / "dsh" / "AGENTS.user-global.md"
BEGIN = "<!-- memorygene:global-auto:begin -->"
END = "<!-- memorygene:global-auto:end -->"
MANIFEST_NAME = ".memorygene-global-auto.json"
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def dsh_home(explicit=None):
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("DSH_HOME")
    return Path(env).expanduser() if env else Path.home() / ".dsh"


def render(values):
    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    missing = PLACEHOLDER.findall(text)
    if missing:
        raise ValueError(f"Unreplaced template placeholders: {sorted(set(missing))}")
    return text


def default_adapter():
    candidates = (
        Path(sys.executable).parent / "memorygene-dsh",
        PROJECT / ".venv" / "bin" / "memorygene-dsh",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return str(candidates[0])


def resolve_paths(args):
    home = dsh_home(args.dsh_home)
    skill_dir = home / "skills" / "memorygene"
    config = Path.home() / ".memorygene" / "dsh.json"
    if not config.is_file():
        config = PROJECT / ".memorygene" / "dsh.json"
    data = {}
    if config.is_file():
        data = json.loads(config.read_text(encoding="utf-8"))
    adapter = data.get("adapter") or default_adapter()
    values = {
        "MG_ADAPTER": adapter,
        "MG_DB": os.environ.get("MEMORYGENE_DB")
        or data.get("db")
        or str(PROJECT / "var" / "memorygene.db"),
        "MG_NAMESPACE": os.environ.get("MEMORYGENE_NAMESPACE")
        or data.get("namespace", "dsh"),
        "MG_SUBJECT": os.environ.get("MEMORYGENE_SUBJECT")
        or data.get("subject", "owner"),
        "MG_CONFIG": str(config),
    }
    return home, skill_dir, config, values


def check(args):
    home, skill_dir, config, values = resolve_paths(args)
    target = home / "AGENTS.md"
    report = {
        "ok": False,
        "dsh_home": str(home),
        "user_skill": str(skill_dir / "SKILL.md"),
        "user_skill_installed": (skill_dir / "SKILL.md").is_file(),
        "global_instructions": str(target),
        "global_instructions_present": target.is_file(),
        "section_present": False,
        "adapter": values["MG_ADAPTER"],
        "adapter_present": Path(values["MG_ADAPTER"]).is_file(),
        "db": values["MG_DB"],
        "db_exists": Path(values["MG_DB"]).is_file(),
        "namespace": values["MG_NAMESPACE"],
        "subject": values["MG_SUBJECT"],
        "manifest": str(home / MANIFEST_NAME),
        "manifest_present": (home / MANIFEST_NAME).is_file(),
        "note": "AGENTS.md is a prompt convention, not an enforced hook; the skill catalog itself is auto-advertised.",
    }
    if target.is_file():
        text = target.read_text(encoding="utf-8")
        report["section_present"] = BEGIN in text and END in text
    report["ok"] = all(
        (
            report["user_skill_installed"],
            report["global_instructions_present"],
            report["section_present"],
            report["adapter_present"],
            report["db_exists"],
        )
    )
    return report


def ensure_user_skill(args):
    home, skill_dir, _, values = resolve_paths(args)
    if (skill_dir / "SKILL.md").is_file():
        return "already-installed"
    installer = PROJECT / "scripts" / "install_dsh_skill.py"
    result = subprocess.run(
        [
            sys.executable,
            str(installer),
            "--target",
            "user",
            "--dsh-home",
            str(home),
            "--adapter",
            values["MG_ADAPTER"],
            "--python",
            sys.executable,
            "--db",
            values["MG_DB"],
            "--namespace",
            values["MG_NAMESPACE"],
            "--subject",
            values["MG_SUBJECT"],
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(
            "Failed to install the user-level skill: "
            + (result.stdout + result.stderr).strip()
        )
    return "installed"


def enable(args):
    home, skill_dir, config, values = resolve_paths(args)
    if not Path(values["MG_ADAPTER"]).is_file():
        raise ValueError(
            f"Adapter not found: {values['MG_ADAPTER']}; install the package first: "
            f"{PROJECT / '.venv' / 'bin' / 'python'} -m pip install -e {PROJECT}"
        )
    skill_state = ensure_user_skill(args)
    target = home / "AGENTS.md"
    section = render(values).strip()
    home.mkdir(parents=True, exist_ok=True)
    backup = None
    mode = "created"
    if target.is_file():
        text = target.read_text(encoding="utf-8")
        has_section = BEGIN in text and END in text
        if has_section:
            mode = "updated"
            text = re.sub(
                re.escape(BEGIN) + r".*?" + re.escape(END),
                section,
                text,
                flags=re.S,
            )
        else:
            if not args.force:
                raise ValueError(
                    f"{target} already exists and has no MemoryGene section. "
                    "Refusing to overwrite your global instructions. Re-run with "
                    "--force to back it up and append the MemoryGene section."
                )
            mode = "appended"
            backup = target.with_name(
                target.name + ".memorygene-backup-" + utc_now().replace(":", "")
            )
            shutil.copy2(target, backup)
            text = text.rstrip() + "\n\n" + section + "\n"
        target.write_text(text, encoding="utf-8")
    else:
        target.write_text(
            "# DeepSeek Harness 全局指令\n\n" + section + "\n", encoding="utf-8"
        )
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    manifest = {
        "mode": mode,
        "target": str(target),
        "backup": str(backup) if backup else None,
        "installed_at": utc_now(),
        "skill_state": skill_state,
        "adapter": values["MG_ADAPTER"],
        "db": values["MG_DB"],
        "namespace": values["MG_NAMESPACE"],
        "subject": values["MG_SUBJECT"],
        "note": "Remove with scripts/install_global_auto.py --uninstall; this does not touch the DSH profile or managed memory.",
    }
    (home / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = check(args)
    report["enabled"] = "ok"
    report["mode"] = mode
    report["backup"] = str(backup) if backup else None
    return report


def uninstall(args):
    home, _, _, _ = resolve_paths(args)
    target = home / "AGENTS.md"
    manifest_path = home / MANIFEST_NAME
    manifest = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed = []
    if target.is_file():
        text = target.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            text = re.sub(
                re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?",
                "",
                text,
                flags=re.S,
            ).strip()
            if text and text != "# DeepSeek Harness 全局指令":
                target.write_text(text + "\n", encoding="utf-8")
                removed.append(f"section in {target}")
            else:
                target.unlink()
                removed.append(str(target))
        else:
            removed.append(f"no MemoryGene section in {target} (left untouched)")
    if manifest_path.is_file():
        manifest_path.unlink()
        removed.append(str(manifest_path))
    return {
        "ok": True,
        "removed": removed,
        "backup": manifest.get("backup"),
        "note": "User-level skill remains installed; remove it with install_dsh_skill.py --target user --uninstall.",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dsh-home", default=None)
    p.add_argument(
        "--force",
        action="store_true",
        help="append to an existing unrelated ~/.dsh/AGENTS.md (backs it up first)",
    )
    p.add_argument("--check", action="store_true")
    p.add_argument("--uninstall", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.check:
            result = check(args)
        elif args.uninstall:
            result = uninstall(args)
        else:
            result = enable(args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
