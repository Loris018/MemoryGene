"""MemoryGene as an MCP server (stdio, JSON-RPC 2.0, standard library only).

Any MCP client (Claude Desktop, Cursor, Cherry Studio, ...) can use the same
memory as the DeepSeek Harness skill. Every tool call is translated into the
corresponding `memorygene-dsh` command, so validation, identity resolution and
"never create a database implicitly" behave exactly as in the adapter.

Start: memorygene-mcp --db PATH [--namespace NS] [--subject USER] [--session ID]
"""

import contextlib
import io
import json
import sys

from . import __version__
from .adapter import COMMANDS, build_parser, normalize_argv, resolve_settings

PROTOCOL_VERSION = "2025-06-18"
GLOBAL_FLAGS = ("--config", "--db", "--namespace", "--subject", "--session")

TEXT = {"type": "string"}
TOPIC = {"type": "string", "description": "stable dotted name, e.g. preference.favorite_flower"}
SCOPE = {"type": "string", "enum": ["persistent", "session"], "default": "persistent"}

TOOLS = [
    {"name": "memory_recall", "command": "recall",
     "description": "Find stored memories by keywords before answering a question about the user. "
                    "Returns values with the user's original words; `unresolved` items are not facts.",
     "properties": {"query": TEXT, "limit": {"type": "integer", "default": 5}}, "required": ["query"]},
    {"name": "memory_current", "command": "current",
     "description": "Read the current value of one topic, with the user's original words as evidence.",
     "properties": {"topic": TOPIC, "scope": SCOPE}, "required": ["topic"]},
    {"name": "memory_history", "command": "history",
     "description": "Read all versions and pending evidence of one topic. Only confirmed entries are past facts.",
     "properties": {"topic": TOPIC, "scope": SCOPE}, "required": ["topic"]},
    {"name": "memory_topics", "command": "topics",
     "description": "List the user's memory topics and their status.", "properties": {}, "required": []},
    {"name": "memory_locate", "command": "locate",
     "description": "Before creating a new topic, find existing topics that may hold the same attribute.",
     "properties": {"topic": TOPIC, "value": TEXT, "source": TEXT}, "required": ["topic", "value"]},
    {"name": "memory_remember", "command": "remember",
     "description": "Store one statement the user made. `source` must be the user's own words. Use "
                    "certainty=uncertain for hedged statements, intent=change only when the user says "
                    "something changed, supplement for 'X is also nice', retract when the user withdraws "
                    "the current value. Read `result.status` and `advice` before telling the user it was saved.",
     "properties": {
         "topic": TOPIC, "value": TEXT, "source": TEXT,
         "certainty": {"type": "string", "enum": ["explicit", "uncertain", "inferred"], "default": "explicit"},
         "intent": {"type": "string", "enum": ["assert", "change", "correct", "supplement", "retract"],
                    "default": "assert"},
         "importance": {"type": "number", "default": 0.7},
         "scope": SCOPE,
         "expires_at": {"type": "string", "description": "only if the user gave an end date (ISO 8601)"},
         "resolves": {"type": "string", "description": "evidence id the user has just confirmed"},
         "update": {"type": "string", "enum": ["confirm", "latest"]},
         "sensitive": {"type": "boolean", "default": False},
         "consent_evidence": {"type": "string", "description": "the user's own words allowing it to be kept"},
     },
     "required": ["topic", "value", "source"]},
    {"name": "memory_profile", "command": "profile",
     "description": "The user's profile: current memories grouped into basic facts, preferences, "
                    "recent situation (expires after 30 days unless mentioned again), life events "
                    "and projects, each with the user's original words.",
     "properties": {}, "required": []},
    {"name": "memory_review", "command": "review",
     "description": "Self-check when the user asks: unresolved evidence, duplicate-looking topics, "
                    "values not supported by the user's words.", "properties": {}, "required": []},
    {"name": "memory_forget", "command": "forget",
     "description": "Delete one topic with all its history, only when the user asks to forget it.",
     "properties": {"topic": TOPIC, "scope": SCOPE}, "required": ["topic"]},
]
BY_NAME = {tool["name"]: tool for tool in TOOLS}


def tool_listing():
    return [{"name": t["name"], "description": t["description"],
             "inputSchema": {"type": "object", "properties": t["properties"],
                             "required": t["required"], "additionalProperties": False}}
            for t in TOOLS]


def argv_for(tool, arguments, base):
    """Translate MCP arguments into adapter command-line arguments."""
    argv = list(base) + [tool["command"]]
    for key, value in arguments.items():
        if key not in tool["properties"]:
            raise ValueError(f"unknown argument: {key}")
        if key == "sensitive":
            if value:
                argv.append("--sensitive")
            continue
        if key == "consent_evidence":
            argv += ["--consent", "--consent-evidence", str(value)]
            continue
        argv += ["--" + key.replace("_", "-"), str(value)]
    return argv


def call_tool(name, arguments, base):
    tool = BY_NAME.get(name)
    if tool is None:
        raise ValueError(f"unknown tool: {name}")
    args = build_parser().parse_args(normalize_argv(argv_for(tool, arguments or {}, base)))
    settings = resolve_settings(args)
    return COMMANDS[args.command](args, settings)


def handle(message, base):
    method, mid = message.get("method"), message.get("id")
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        return {"protocolVersion": requested, "capabilities": {"tools": {}},
                "serverInfo": {"name": "memorygene", "version": __version__}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_listing()}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            # argparse reports errors on stderr and exits; keep stdout clean for JSON-RPC.
            with contextlib.redirect_stderr(io.StringIO()):
                result = call_tool(params.get("name"), params.get("arguments"), base)
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "isError": False}
        except (ValueError, TypeError, KeyError, OSError, SystemExit) as exc:
            text = json.dumps({"ok": False, "error": str(exc) or type(exc).__name__}, ensure_ascii=False)
            return {"content": [{"type": "text", "text": text}], "isError": True}
    if mid is None:
        return None  # notifications need no reply
    raise LookupError(method)


def serve(stdin, stdout, base):
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            mid = message.get("id")
            try:
                result = handle(message, base)
                if result is None and mid is None:
                    continue
                reply = {"jsonrpc": "2.0", "id": mid, "result": result}
            except LookupError:
                reply = {"jsonrpc": "2.0", "id": mid,
                         "error": {"code": -32601, "message": "method not found"}}
        stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        stdout.flush()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    base = []
    i = 0
    while i < len(argv):
        if argv[i] in GLOBAL_FLAGS and i + 1 < len(argv):
            base += [argv[i], argv[i + 1]]
            i += 2
        else:
            raise SystemExit(f"memorygene-mcp: unexpected argument {argv[i]}")
    serve(sys.stdin, sys.stdout, base)


if __name__ == "__main__":
    main()
