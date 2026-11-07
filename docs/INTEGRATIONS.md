# Using MemoryGene with other LLM clients

MemoryGene keeps memory outside the model, so any client that can call tools can use it. All clients below share the same database when they point to the same file. Create the database once:

```sh
.venv/bin/python -c "from memorygene import MemoryStore; MemoryStore('var/memorygene.db').close()"
.venv/bin/memorygene-dsh --db "$PWD/var/memorygene.db" doctor   # check paths and identity
```

## MCP clients (Claude Desktop, Cursor, Cherry Studio, ...)

`memorygene-mcp` is an MCP server over stdio, written with the Python standard library only. It exposes the tools `memory_recall`, `memory_current`, `memory_history`, `memory_topics`, `memory_locate`, `memory_remember`, `memory_review` and `memory_forget`. Each call goes through the same checks as the command-line adapter.

Claude Desktop (`claude_desktop_config.json`) and Cursor (`~/.cursor/mcp.json`) use the same format:

```json
{
  "mcpServers": {
    "memorygene": {
      "command": "<project>/.venv/bin/memorygene-mcp",
      "args": ["--db", "<project>/var/memorygene.db", "--namespace", "mcp", "--subject", "owner"]
    }
  }
}
```

Cherry Studio: Settings → MCP Servers → Add → type `stdio`, command `<project>/.venv/bin/memorygene-mcp`, arguments as above.

The server never creates a database by itself. Clients that support it can pass `--session <id>` to enable session-scoped memory.

## Skill-based agents (Claude Code, Codex)

```sh
.venv/bin/python scripts/install_skill.py --host claude-code   # ~/.claude/skills/memorygene/SKILL.md
.venv/bin/python scripts/install_skill.py --host codex         # ~/.codex/skills/memorygene/SKILL.md
.venv/bin/python scripts/install_skill.py --host codex --uninstall
```

The skill tells the agent to call `memorygene-dsh`, which finds the database through `~/.memorygene/dsh.json`, `MEMORYGENE_DB` or `--config`. The installer only replaces or removes files it wrote itself.

## DeepSeek Harness

See [DSH-INTEGRATION.md](DSH-INTEGRATION.md).

## Status

The MCP server is covered by protocol-level tests (handshake, tool listing, reads, writes, errors). The DeepSeek Harness integration has also been verified in real cross-session use. Real sessions in Claude Desktop, Cursor, Cherry Studio, Claude Code and Codex have not been run yet.
