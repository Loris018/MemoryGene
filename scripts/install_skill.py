#!/usr/bin/env python3
"""Install the host-neutral MemoryGene skill for Claude Code or Codex.

The skill file is rendered from skills/generic/SKILL.md with this project's
adapter path. The adapter finds the database through ~/.memorygene/dsh.json
(written by scripts/install_dsh_skill.py) or MEMORYGENE_DB / --config.

  python scripts/install_skill.py --host claude-code          # ~/.claude/skills/memorygene
  python scripts/install_skill.py --host codex                # ~/.codex/skills/memorygene
  python scripts/install_skill.py --host codex --dest DIR     # custom skills directory
  python scripts/install_skill.py --host codex --uninstall

Only files this script wrote (marked `memorygene-installed: true`) are
replaced or removed; any other existing file is left untouched.
"""

import argparse
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT / "skills" / "generic" / "SKILL.md"
MARKER = "memorygene-installed: true"
HOSTS = {"claude-code": Path.home() / ".claude" / "skills",
         "codex": Path.home() / ".codex" / "skills"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", choices=sorted(HOSTS), required=True)
    parser.add_argument("--dest", type=Path, default=None, help="skills directory override")
    parser.add_argument("--adapter", default=str(PROJECT / ".venv" / "bin" / "memorygene-dsh"))
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    target = (args.dest or HOSTS[args.host]) / "memorygene" / "SKILL.md"
    if target.exists() and MARKER not in target.read_text("utf-8"):
        print(f"refusing to touch {target}: not written by this installer", file=sys.stderr)
        return 2
    if args.uninstall:
        if target.exists():
            target.unlink()
            try:
                target.parent.rmdir()
            except OSError:
                pass
        print(f"removed {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE.read_text("utf-8").replace("{{MG_ADAPTER}}", args.adapter), "utf-8")
    print(f"installed {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
