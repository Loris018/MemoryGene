# Live headless probe — summary and raw evidence index

All runs used the installed Electron app's CLI:

```
/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh --version
# 0.2.1-rc.2
```

Common invocation shape (run from the session cwd; this is what determines the
Session working directory, see `dsh-headless/lib/index.js:316`):

```
cd <cwd> && /Applications/DeepSeek\ Harness.app/Contents/Resources/runtime/cli/bin/dsh \
  --profile headless --patch /tmp/dsh-mg-headless.patch.yml --json "<prompt>"
```

`/tmp/dsh-mg-headless.patch.yml` restores the already-signed-in DeepSeek account
for headless runs (4 rows: `credentials`, `deepseek-account`, `authorization`,
`agent-default-model` → `deepseek-account` / `deepseek-flash`). It is a
`--patch` overlay only; it writes nothing into the Desktop profile.

Budget: **5 of the allowed 5 headless model runs used**, all `deepseek-flash`,
each a single short prompt. No run failed.

## Runs

| # | purpose | cwd | session id | expected | observed |
|---|---|---|---|---|---|
| 1 | positive: throwaway skill discovered | `/tmp/mg-probe-project` (git repo, `.dsh/skills/dsh-probe-dummy/SKILL.md`) | `session-510a6e7c-4915-4e96-94d8-18f044897f02` | `skill` tool loads it | tool_call `skill {name:"dsh-probe-dummy"}` → `status:"completed"`, body + base dir returned, final `MGPROBE-NONCE-7F3A9C` |
| 2 | negative control: no skill | `/tmp/mg-probe-control` (no roots) | `session-08abee69-2213-4211-8730-8a3a2ada6f8e` | absent | tool_call `skill` → `status:"error"`, `Error: skill "dsh-probe-dummy" is unknown or no longer available`; **0** `skill-catalog` messages |
| 3 | project root = nearest `.git` ancestor | `/tmp/mg-probe-project/sub` | `session-a9843874-ba91-437a-aec5-466210d20f3a` | discovered via parent `.git` | loaded; base dir `/private/tmp/mg-probe-project/.dsh/skills/dsh-probe-dummy` |
| 4 | production path: Lead-installed real skill | the real MemoryGene project (git repo) | `session-c7af3dac-422d-4659-9f85-65ff1b23442e` | discovered | loaded `<skill_content name="memorygene">`, base dir `<MemoryGene>/.dsh/skills/memorygene`; final answer = the `memorygene-dsh` adapter path from its body |
| 5 | `AGENTS.md` auto-injection (the other project-scoped channel) | `/tmp/mg-probe-project` (with fictional `AGENTS.md`) | `session-e4995f1e-ffb8-4572-bb06-ed6fd294abc1` | marker in context | session log has a `user/message` with `source.kind="agent-instructions"` (seq 9) containing the file; final `AGENTS-MARKER-9B2E` |

Deterministic proof, not model-answer trust: after each run, the persisted
Zstandard session log was decompressed and the injected messages were read
directly (they are ordinary durable `user/message` events). Files (the decompressed
session logs are kept locally but not published, because they embed the host's own system
prompt and tool schemas; the stdout/stderr logs and extracts below are published):

| run | raw stdout/stderr | decompressed session log | injected-message extract |
|---|---|---|---|
| 1 | `live-probe-positive.stdout.log`, `.stderr.log` | `live-probe-positive.session.jsonl` | `live-probe-catalog-evidence.md` (§positive) |
| 2 | `live-probe-negative.*` | `live-probe-negative.session.jsonl` | `live-probe-catalog-evidence.md` (§negative) |
| 3 | `live-probe-subdir.*` | `live-probe-subdir.session.jsonl` | `live-probe-catalog-evidence.md` (§subdir) |
| 4 | `live-probe-real-project.*` | `live-probe-real-project.session.jsonl` | `live-probe-catalog-evidence.md` (§real-project) |
| 5 | `live-probe-agents-md.*` | `live-probe-agents-md.session.jsonl` | catalog-evidence note in this file |

## Persisted session paths and the decompression command

Sessions are stored under `$DSH_HOME/sessions` (`~/.dsh/sessions` in this
install; the headless profile sets `session-persistence-jsonl.root` to
`dshHomePath('sessions')`), one directory per normalized cwd, then one
directory per session id (`dsh-session-persistence-jsonl/README.md:57-73`):

```
~/.dsh/sessions/--private-tmp-mg-probe-project--/session-510a6e7c-4915-4e96-94d8-18f044897f02/session.v4.jsonl.zstd
~/.dsh/sessions/--private-tmp-mg-probe-control--/session-08abee69-2213-4211-8730-8a3a2ada6f8e/session.v4.jsonl.zstd
~/.dsh/sessions/--private-tmp-mg-probe-project-sub--/session-a9843874-ba91-437a-aec5-466210d20f3a/session.v4.jsonl.zstd
~/.dsh/sessions/--<repo>--/session-c7af3dac-422d-4659-9f85-65ff1b23442e/session.v4.jsonl.zstd
~/.dsh/sessions/--private-tmp-mg-probe-project--/session-e4995f1e-ffb8-4572-bb06-ed6fd294abc1/session.v4.jsonl.zstd
```

```
zstd -d -c <session.v4.jsonl.zstd> > session.jsonl
```

## Run 5: `agent-instructions` message (fictional probe content)

Injected as a durable `user/message` with `source.kind = "agent-instructions"`,
immediately after the claimed user prompt and before the skill catalog:

```text
<system-reminder>
The following workspace instructions may be relevant to your work. Use them as guidance when applicable. More specific instructions take precedence over broader ones. They do not override system, developer, or direct user instructions.

Instructions from: AGENTS.md

# Dummy probe workspace instructions
...
AGENTS-MARKER-9B2E
...
</system-reminder>
```

Source: `@deepseek-ai/dsh-agent-instructions` (`lib/index.js:1222` apply,
`:1406` `agent/pre-step` listener, `:673-674` project-root → cwd file chain,
`:17` default candidates `AGENTS.md`, `CLAUDE.md`, README lines 34-42).
The headless profile mounts it globally (row `agent-instructions`,
`maxBytes: 65536`, in the composed headless config); Web/Desktop mount it
inside the `standard` agent preset, which is visible in the Web profile dump
(`dsh --profile web --dump-config`, the `preset-standard` row) and explained in
`research.md` §4.

## Extra L1 observation: the live Desktop GUI session (0 model runs)

Not a headless run, but the strongest GUI-side evidence available without touching
the Desktop profile. The current GUI session
(`DSH_SESSION_ID=7fec6827-6797-48ae-8b21-5c1006d1798e`, header cwd `~`,
`DSH_PROFILE=desktop`) was recorded while this task ran. Reading its own persisted log:

- `skill-catalog` seq 11: initial catalog = the 7 `office` skills only;
- `skill-catalog` seq 986: a full **replacement** catalog (`update: true`) adding
  `memorygene`, appended live by the host watcher after the Lead installed
  `~/.dsh/skills/memorygene` at 15:32 (user-dsh root, rank 400);
- a real GUI `skill({name:"memorygene"})` call returned
  `Base directory for this skill: ~/.dsh/skills/memorygene`.

So the Desktop self-hosted Web session really does mount `skill-filesystem` +
`tool-skill` and receive live catalog replacement. What remains open is only the
project-root variant (`<projectRoot>/.dsh/skills`, rank 100), which needs the session
cwd to be inside the project — see `research.md` §7.6 and §8 (limitation 1).

Extracted deterministically into `gui-live-catalog-evidence.md` (catalog entries and
the tool result's base-directory line only; no personal content).

## Scratch fixtures (throwaway, under /tmp only)

```
/tmp/mg-probe-project/                       git repo
  AGENTS.md                                  fictional marker AGENTS-MARKER-9B2E
  .dsh/skills/dsh-probe-dummy/SKILL.md       fictional marker MGPROBE-NONCE-7F3A9C
  sub/                                       git-repo subdirectory used by run 3
/tmp/mg-probe-control/                       git repo, no skill roots
```

Nothing in the real MemoryGene project (other than files under `evidence/dsh/`)
and nothing in `~/.dsh` config/plugins/credentials was modified by these runs.
Run 4 only *read* the Lead-installed skill.
