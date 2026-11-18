#!/usr/bin/env python3
"""Deterministic DeepSeek Harness filesystem-skill discovery probe (no LLM, no network).

What it answers
---------------
Given a working directory (a DSH session's cwd), would DSH 0.2.1-rc.2 discover
the skill files under the documented roots, and which one would win a name
conflict? Given one concrete skill file, would a session with a given cwd
discover exactly that file?

Evidence level (read this before trusting output)
-------------------------------------------------
L2 - rule reimplementation, not the real provider.
This script reimplements the algorithm of the *installed* packages as read from
the Electron app's `app.asar` (same version string, `dsh --version` =
0.2.1-rc.2). It does not import the real provider: those packages live inside
`app.asar`, which plain Node/Python cannot load without extracting the whole
runtime tree. Real `dsh --profile headless` sessions were used separately to
confirm that the `skill-catalog` message and the loaded skill body appear.

Source of the rules (package/lib/index.js of the installed app)
---------------------------------------------------------------
`@deepseek-ai/dsh-skill-filesystem/lib/index.js`:
  * ranks + root table ............ roots()               lines 150-188
    (100 <projectRoot>/.dsh/skills, 200 <projectRoot>/.agents/skills,
     300 customSkillDirs, 400 <dshHome>/skills [skip `.system`],
     500 <agentsHome>/skills, 600 bundledSkillDir)
  * config defaults ............... Config                 lines 31-44
  * entry shape ................... discoverRoot()         lines 585-618
    (directory bundle `<name>/SKILL.md`, flat `<name>.md`; one level deep only)
  * frontmatter + validation ...... parseSkillFile()       lines 668-709
    (required name+description, kebab-case name, invocation keys)
  * boolean grammar ............... frontmatterBoolean()   lines 867-882
  * project root .................. findProjectRoot()      lines 811-819
    (nearest ancestor containing `.git`, else the cwd)
`@deepseek-ai/dsh-skill/lib/index.js`:
  * name grammar .................. SKILL_NAME / isSkillName() lines 17-31
  * rank-first winner ............. compareIndexedCandidates / collectLayer()
                                                     lines 312-330, 519-521
`@deepseek-ai/dsh-skill-filesystem/README.md` documents the same table
("Roots and priority", "Skill format", "Known Limitations") at lines 36-56 and
145-151.

Deliberate approximations (documented, not bugs)
------------------------------------------------
  * Entries are sorted by name with Python's default (code-point) order; the
    original uses `localeCompare`. The difference only affects which duplicate
    name wins when two files inside the SAME root+tier declare the same name.
  * Only the local filesystem provider is modelled. The registry can also merge
    other providers (bundled office skills, runtime skills, agent-preset scope
    layers); this probe answers only "what does skill-filesystem discover for
    this cwd".
  * Frontmatter is parsed with full YAML (PyYAML); when PyYAML is unavailable a
    flat `key: value` fallback is used and the run reports `yaml_mode:
    "flat-fallback"`, which cannot parse nested `metadata:` blocks.

Usage
-----
  python3 tools/dsh/probe_skills.py                     # list catalog for $PWD
  python3 tools/dsh/probe_skills.py --cwd /path/to/proj
  python3 tools/dsh/probe_skills.py --cwd /path/to/proj \
      --skill /path/to/proj/.dsh/skills/foo/SKILL.md    # exit 0 iff that file wins
  python3 tools/dsh/probe_skills.py --json              # machine readable
  ... --custom-dir DIR (repeatable) --bundled-dir DIR --no-default-roots
  ... --dsh-home DIR --agents-home DIR

Exit codes
----------
  0  list mode: discovery ran.  skill mode: the named file is a valid,
     discoverable, winning candidate for the given cwd.
  1  skill mode: file missing, invalid frontmatter, outside every scanned root
     locator, or shadowed by a higher-priority skill with the same name.
  2  usage error / bad argument.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

try:  # full YAML like the provider's `yaml` package
    import yaml  # type: ignore

    _YAML_MODE = "pyyaml"
except Exception:  # pragma: no cover - environment dependent
    yaml = None  # type: ignore
    _YAML_MODE = "flat-fallback"

SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# rank / source / path-builder, mirroring dsh-skill-filesystem/lib/index.js:150-188
PROJECT_DSH_RANK = 100
PROJECT_AGENTS_RANK = 200
CUSTOM_RANK = 300
USER_DSH_RANK = 400
USER_AGENTS_RANK = 500
BUNDLED_SKILL_RANK = 600

LEGACY_INVOCATION_KEYS = (
    ("disableModelInvocation", "disable-model-invocation"),
    ("modelInvocable", "disable-model-invocation"),
    ("userInvocable", "user-invocable"),
)


@dataclass
class Root:
    path: str
    source: str
    rank: int
    project_root: str | None = None
    skip_system: bool = False
    trusted_host: bool = False
    index: int = 0  # global scan order (provider localOrder)


@dataclass
class Candidate:
    name: str
    description: str
    when_to_use: str | None
    invocation: dict
    source: str
    rank: int
    path: str  # resolved instruction file path
    root: str
    order: int
    metadata: dict | None = None
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        out = {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "rank": self.rank,
            "path": self.path,
            "root": self.root,
            "invocation": self.invocation,
        }
        if self.when_to_use is not None:
            out["whenToUse"] = self.when_to_use
        if self.metadata is not None:
            out["metadata"] = self.metadata
        return out


class Probe:
    def __init__(
        self,
        cwd: str,
        dsh_home: str,
        agents_home: str,
        custom_dirs: list[str],
        bundled_dir: str | None,
        include_default_roots: bool = True,
    ) -> None:
        self.cwd = os.path.realpath(os.path.abspath(cwd))
        self.dsh_home = os.path.expanduser(dsh_home)
        self.agents_home = os.path.expanduser(agents_home)
        self.custom_dirs = [os.path.realpath(os.path.abspath(d)) for d in custom_dirs]
        self.bundled_dir = (
            os.path.realpath(os.path.abspath(os.path.expanduser(bundled_dir)))
            if bundled_dir
            else None
        )
        self.include_default_roots = include_default_roots
        self.warnings: list[str] = []
        self.project_root = self.find_project_root(self.cwd) if include_default_roots else None

    # --- project root: nearest ancestor containing .git, else cwd -----------
    @staticmethod
    def find_project_root(cwd: str) -> str:
        current = os.path.realpath(cwd)
        while True:
            if os.access(os.path.join(current, ".git"), os.F_OK):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                return os.path.realpath(cwd)
            current = parent

    # --- root table ---------------------------------------------------------
    def roots(self) -> list[Root]:
        out: list[Root] = []
        if self.include_default_roots and self.project_root is not None:
            out.append(
                Root(
                    path=os.path.join(self.project_root, ".dsh", "skills"),
                    source="project-dsh",
                    rank=PROJECT_DSH_RANK,
                    project_root=self.project_root,
                )
            )
            out.append(
                Root(
                    path=os.path.join(self.project_root, ".agents", "skills"),
                    source="project-agents",
                    rank=PROJECT_AGENTS_RANK,
                    project_root=self.project_root,
                )
            )
        for path in self.custom_dirs:
            out.append(Root(path=path, source="custom", rank=CUSTOM_RANK))
        if self.include_default_roots:
            out.append(
                Root(
                    path=os.path.join(self.dsh_home, "skills"),
                    source="user-dsh",
                    rank=USER_DSH_RANK,
                    skip_system=True,
                )
            )
            out.append(
                Root(
                    path=os.path.join(self.agents_home, "skills"),
                    source="user-agents",
                    rank=USER_AGENTS_RANK,
                )
            )
        if self.bundled_dir is not None:
            out.append(
                Root(
                    path=self.bundled_dir,
                    source="bundled",
                    rank=BUNDLED_SKILL_RANK,
                    trusted_host=True,
                )
            )
        for index, root in enumerate(out):
            root.index = index
        return out

    # --- one root: direct children only ------------------------------------
    def discover_root(self, root: Root) -> list[Candidate]:
        try:
            names = sorted(os.listdir(root.path))
        except OSError as error:
            if error.errno in (2, 20):  # ENOENT, ENOTDIR -> valid empty state
                return []
            raise
        found: list[Candidate] = []
        for name in names:
            if root.skip_system and name == ".system":
                continue
            entry = os.path.join(root.path, name)
            try:
                is_dir = os.path.isdir(entry)
                is_file = os.path.isfile(entry)
            except OSError:  # pragma: no cover - race
                continue
            if is_dir:
                locator = os.path.join(entry, "SKILL.md")
            elif is_file and name.endswith(".md"):
                locator = entry
            else:
                continue
            parsed = self.parse_skill_file(locator)
            if parsed is None:
                continue
            found.append(
                Candidate(
                    name=parsed["name"],
                    description=parsed["description"],
                    when_to_use=parsed["whenToUse"],
                    invocation=parsed["invocation"],
                    source=root.source,
                    rank=root.rank,
                    path=parsed["path"],
                    root=root.path,
                    order=root.index,
                    metadata=parsed["metadata"],
                    warnings=parsed["warnings"],
                )
            )
        return found

    # --- frontmatter + validation ------------------------------------------
    def parse_skill_file(self, path: str) -> dict | None:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                raw = handle.read()
        except OSError as error:
            if error.errno in (2, 20):
                return None
            raise
        parsed = self.parse_frontmatter(raw)
        if parsed is None:
            self.warn(f"skill file {path} ignored: missing YAML frontmatter")
            return None
        data, _body = parsed
        name = string_field(data, "name")
        description = string_field(data, "description")
        if name is None or description is None:
            self.warn(f"skill file {path} ignored: frontmatter requires name and description")
            return None
        if not SKILL_NAME_RE.match(name):
            self.warn(f'skill file {path} ignored: invalid skill name "{name}"')
            return None
        invocation = self.parse_invocation_policy(data)
        if invocation is None:
            self.warn(f"skill file {path} ignored: invalid invocation frontmatter")
            return None
        local: list[str] = [w for w in self.warnings if path in w]
        return {
            "name": name,
            "description": description,
            "whenToUse": optional_string(data, "whenToUse"),
            "invocation": invocation,
            "metadata": data.get("metadata")
            if isinstance(data.get("metadata"), dict)
            else None,
            "path": os.path.realpath(path),
            "warnings": local,
        }

    @staticmethod
    def parse_frontmatter(raw: str) -> tuple[dict, str] | None:
        first_newline = raw.find("\n")
        if first_newline < 0:
            return None
        if raw[:first_newline].rstrip("\r") != "---":
            return None
        start = first_newline + 1
        line_start = start
        while line_start <= len(raw):
            next_newline = raw.find("\n", line_start)
            line_end = len(raw) if next_newline < 0 else next_newline
            if raw[line_start:line_end].rstrip("\r") == "---":
                body_start = len(raw) if next_newline < 0 else next_newline + 1
                header = raw[start:line_start]
                return _load_yaml_mapping(header), raw[body_start:]
            if next_newline < 0:
                return None
            line_start = next_newline + 1
        return None

    def parse_invocation_policy(self, data: dict) -> dict | None:
        for legacy, canonical in LEGACY_INVOCATION_KEYS:
            if legacy in data:
                self.warn(
                    f'frontmatter field "{legacy}" is unsupported; use "{canonical}"'
                )
                return None
        disable_model = frontmatter_boolean(data, "disable-model-invocation")
        if disable_model is _INVALID:
            return None
        user_invocable = frontmatter_boolean(data, "user-invocable")
        if user_invocable is _INVALID:
            return None
        return {
            "modelInvocable": disable_model is not True,
            "userInvocable": user_invocable is not False,
        }

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    # --- merge: rank first, then scan order; first wins ---------------------
    def catalog(self) -> tuple[list[Candidate], list[dict]]:
        candidates: list[Candidate] = []
        for root in self.roots():
            candidates.extend(self.discover_root(root))
        candidates.sort(key=lambda c: (c.rank, c.order))
        winners: dict[str, Candidate] = {}
        shadowed: list[dict] = []
        for candidate in candidates:
            current = winners.get(candidate.name)
            if current is None:
                winners[candidate.name] = candidate
            else:
                shadowed.append(
                    {
                        "name": candidate.name,
                        "kept": current.path,
                        "ignored": candidate.path,
                        "reason": "higher-priority skill already exists",
                    }
                )
                self.warn(
                    f'skill "{candidate.name}" from {candidate.source} ignored because a '
                    "higher-priority skill already exists"
                )
        return sorted(winners.values(), key=lambda c: c.name), shadowed


_INVALID = object()


def _load_yaml_mapping(header: str) -> dict:
    if yaml is not None:
        try:
            loaded = yaml.safe_load(header)
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    out: dict[str, Any] = {}
    for line in header.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, _, value = line.partition(":")
        text = value.strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1]
        if text in ("true", "false"):
            out[key.strip()] = text == "true"
        else:
            out[key.strip()] = text
    return out


def string_field(data: dict, key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and len(value) > 0 else None


def optional_string(data: dict, key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and len(value) > 0 else None


def frontmatter_boolean(data: dict, key: str):
    if key not in data:
        return None
    value = data[key]
    if isinstance(value, bool):
        return value
    if value in (1, "1") and not isinstance(value, bool):
        return True
    if value in (0, "0") and not isinstance(value, bool):
        return False
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("true", "yes", "on"):
            return True
        if lowered in ("false", "no", "off"):
            return False
    return _INVALID


def check_skill(
    probe: Probe, skill_path: str, catalog: list[Candidate], shadowed: list[dict]
) -> dict:
    target = os.path.realpath(os.path.abspath(skill_path))
    result: dict[str, Any] = {
        "skill_file": target,
        "cwd": probe.cwd,
        "project_root": probe.project_root,
        "discovered": False,
        "winning": False,
    }
    if not os.path.isfile(target):
        result["error"] = "file does not exist"
        return result
    parsed = probe.parse_skill_file(target)
    if parsed is None:
        result["error"] = "invalid or missing frontmatter (see warnings)"
        result["warnings"] = probe.warnings
        return result
    result["name"] = parsed["name"]
    result["description"] = parsed["description"]
    result["invocation"] = parsed["invocation"]

    # Which scanned root locator does this file answer, if any?
    matched_root: Root | None = None
    for root in probe.roots():
        root_dir = os.path.realpath(root.path)
        parent = os.path.dirname(target)
        if os.path.basename(target) == "SKILL.md" and os.path.dirname(parent) == root_dir:
            matched_root = root
        elif target.lower().endswith(".md") and parent == root_dir:
            matched_root = root
        if matched_root is not None:
            break
    result["root"] = matched_root.path if matched_root else None
    result["rank"] = matched_root.rank if matched_root else None
    result["source"] = matched_root.source if matched_root else None
    if matched_root is None:
        result["error"] = (
            "file is not a locator of any scanned root for this cwd (discovery is "
            "one level deep: <root>/<name>/SKILL.md or <root>/<name>.md)"
        )
        return result
    result["discovered"] = True
    win = next((c for c in catalog if c.path == target), None)
    if win is not None:
        result["winning"] = True
    else:
        clash = next((c for c in catalog if c.name == parsed["name"]), None)
        result["shadowed_by"] = clash.path if clash else None
        if clash is None:
            result["error"] = "not present in the merged catalog (unexpected)"
        else:
            result["error"] = (
                f'same name "{parsed["name"]}" is already provided by {clash.path} '
                f"(rank {clash.rank})"
            )
    result["warnings"] = probe.warnings
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic DSH 0.2.1-rc.2 filesystem-skill discovery probe "
            "(L2: rule reimplementation; live sessions were checked separately)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cwd", default=os.getcwd(), help="session cwd to probe (default: $PWD)")
    parser.add_argument("--skill", help="check one skill file against --cwd; exit 0 iff it wins")
    parser.add_argument("--dsh-home", default=os.environ.get("DSH_HOME") or "~/.dsh")
    parser.add_argument(
        "--agents-home", default=os.environ.get("DSH_AGENTS_HOME") or "~/.agents"
    )
    parser.add_argument(
        "--custom-dir", action="append", default=[], help="repeatable customSkillDirs entry"
    )
    parser.add_argument("--bundled-dir", default=None, help="bundledSkillDir (rank 600)")
    parser.add_argument(
        "--no-default-roots", action="store_true", help="only custom/bundled roots"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.cwd):
        print(f"error: --cwd is not a directory: {args.cwd}", file=sys.stderr)
        return 2

    probe = Probe(
        cwd=args.cwd,
        dsh_home=args.dsh_home,
        agents_home=args.agents_home,
        custom_dirs=args.custom_dir,
        bundled_dir=args.bundled_dir,
        include_default_roots=not args.no_default_roots,
    )
    roots = probe.roots()
    catalog, shadowed = probe.catalog()

    if args.skill:
        result = check_skill(probe, args.skill, catalog, shadowed)
        result["evidence_level"] = "L2-rule-reimplementation"
        result["yaml_mode"] = _YAML_MODE
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"cwd:            {result['cwd']}")
            print(f"project root:   {result['project_root']}")
            print(f"skill file:     {result['skill_file']}")
            if "name" in result:
                print(f"name:           {result['name']}")
            if result.get("root"):
                print(f"root:           {result['root']} (rank {result['rank']}, {result['source']})")
            print(f"discovered:     {result['discovered']}")
            print(f"winning:        {result['winning']}")
            if result.get("error"):
                print(f"error:          {result['error']}")
            for warning in result.get("warnings", []):
                print(f"warning:        {warning}")
            print("evidence level: L2 (rule reimplementation of the installed provider)")
        return 0 if result.get("winning") else 1

    payload = {
        "cwd": probe.cwd,
        "project_root": probe.project_root,
        "roots": [
            {
                "rank": root.rank,
                "source": root.source,
                "path": root.path,
                "exists": os.path.isdir(root.path),
            }
            for root in roots
        ],
        "skills": [c.summary() for c in catalog],
        "shadowed": shadowed,
        "warnings": probe.warnings,
        "evidence_level": "L2-rule-reimplementation",
        "yaml_mode": _YAML_MODE,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"cwd:            {probe.cwd}")
    print(f"project root:   {probe.project_root}")
    print("scanned roots (rank order):")
    for row in payload["roots"]:
        mark = "present" if row["exists"] else "missing"
        print(f"  {row['rank']:>3}  {row['source']:<15} {row['path']}  [{mark}]")
    print(f"discovered skills: {len(catalog)}")
    for skill in catalog:
        print(
            f"  - {skill.name}  (rank {skill.rank}, {skill.source})"
            f"  path={skill.path}"
        )
        print(f"      {skill.description}")
    for entry in shadowed:
        print(f"  shadowed: {entry['ignored']} (kept {entry['kept']})")
    for warning in probe.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print("evidence level: L2 (rule reimplementation of the installed provider)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
