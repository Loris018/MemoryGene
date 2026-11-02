"""Entirely fictional, deterministic example with no persistent user database."""

import json
from dataclasses import replace

from memorygene import Candidate, MemoryStore

NOW = "2026-10-24T10:00:00Z"
with MemoryStore() as memory:
    first = Candidate(
        "demo",
        "fictional-user",
        "preference.favorite_flower",
        "玫瑰",
        "虚构用户：最喜欢玫瑰。",
        "2026-10-01T00:00:00Z",
    )
    memory.ingest(first, "day-1", now=NOW)
    hint = replace(
        first,
        value="栀子花",
        source="虚构用户：栀子花也挺好看。",
        certainty="uncertain",
        intent="supplement",
        at="2026-10-10T00:00:00Z",
    )
    memory.ingest(hint, "day-10", now=NOW)
    changed = replace(
        hint,
        source="虚构用户：现在最喜欢栀子花。",
        certainty="explicit",
        intent="change",
        at="2026-10-20T00:00:00Z",
    )
    memory.ingest(changed, "day-20", now=NOW, resolves="day-10")
    current = memory.current("demo", "fictional-user", first.topic, now=NOW)
    history = memory.history("demo", "fictional-user", first.topic, now=NOW)
    assert current["candidate"]["value"] == "栀子花"
    assert [e["candidate"]["value"] for e in history if e["status"] == "confirmed"] == [
        "玫瑰",
        "栀子花",
    ]
    print(
        json.dumps(
            {"current": current, "history": history}, ensure_ascii=False, indent=2
        )
    )
