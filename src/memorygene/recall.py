"""Budgeted discovery of current facts; no usage reinforcement or writes.

Original lexical implementation inspired by progressive-disclosure interfaces.
This is not semantic search: Chinese bigrams and other Unicode words must overlap.
The budget covers the entire compact JSON response plus its newline, in Unicode
characters (not model tokens or UTF-8 bytes).
"""

import re
import unicodedata

from .codec import IntegrityError
from .core import canonical, instant, now_string

_PARTS = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+|[^\W_]+", re.UNICODE)


def terms(text):
    parts = _PARTS.findall(unicodedata.normalize("NFKC", text).casefold())
    out = set()
    for part in parts:
        if "\u3400" <= part[0] <= "\u9fff" and len(part) > 1:
            out.update(part[i:i + 2] for i in range(len(part) - 1))
        else:
            out.add(part)
    return out


def recall(store, namespace, subject, query, *, now=None, visible_session="",
           limit=5, budget_chars=2000):
    """Return current, unexpired, scoped candidates, then fetch via current.

    Empty visible_session means persistent only; None is deliberately forbidden.
    Like current(), this validates touched records, not all history/head rollback;
    verify() remains the explicit whole-store audit. Scan cost is linear in heads.
    """
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
        raise ValueError("query must contain 1 to 1000 characters")
    query_terms = terms(query)
    if not query_terms:
        raise ValueError("query must contain searchable words or Chinese text")
    for label, value, low, high in (
        ("limit", limit, 1, 20), ("budget_chars", budget_chars, 256, 20000),
    ):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{label} must be an integer in [{low}, {high}]")
    if not isinstance(visible_session, str):
        raise ValueError("visible_session must be text; empty means persistent only")
    namespace = unicodedata.normalize("NFC", namespace)
    subject = unicodedata.normalize("NFC", subject)
    clock = instant(now or now_string())
    ranked = []
    rows = store.db.execute(
        "SELECT h.route AS head_route, e.* FROM heads h "
        "LEFT JOIN events e ON e.id=h.event_id ORDER BY h.route"
    )
    for row in rows:
        ns, subj, topic, scope, session = store._route_parts(row["head_route"])
        if ns != namespace or subj != subject:
            continue
        if scope == "session" and (not visible_session or session != visible_session):
            continue
        # Excluded users/sessions are never decoded or searched for content.
        if row["id"] is None or row["route"] != row["head_route"]:
            raise IntegrityError("Head points to missing or misrouted evidence")
        event = store._read(row)
        if event["status"] == "retracted":
            continue
        if event["status"] != "confirmed":
            raise IntegrityError("Head points to unconfirmed evidence")
        if not store._live(event, clock):
            continue
        c = event["candidate"]
        overlaps = {
            field: query_terms & terms(c[field])
            for field in ("topic", "value", "source")
        }
        score = sum(len(overlaps[f]) * weight for f, weight in (
            ("topic", 3), ("value", 2), ("source", 1),
        ))
        if not score:
            continue
        ranked.append((score, {
            "id": event["id"], "topic": topic, "scope": scope,
            "preview": c["value"][:120], "preview_truncated": len(c["value"]) > 120,
            "matched_fields": [f for f, overlap in overlaps.items() if overlap],
        }))
    # No recency boost: an old, relevant fact can outrank recent distractions.
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["topic"], pair[1]["scope"], pair[1]["id"]))
    # Unresolved pending/conflict evidence is surfaced separately and labelled,
    # so the agent can mention an open question without treating it as a fact.
    from .reconsolidate import open_evidence, slots

    unresolved = []
    for slot in slots(store, namespace, subject, now=clock.isoformat(),
                      visible_session=visible_session):
        for event in open_evidence(slot, now=clock.isoformat()):
            c = event["candidate"]
            hit = query_terms & (terms(slot["topic"]) | terms(c["value"]) | terms(c["source"]))
            if hit:
                unresolved.append((len(hit), {
                    "id": event["id"], "topic": slot["topic"], "scope": slot["scope"],
                    "status": event["status"], "preview": c["value"][:120],
                    "current": slot["head"]["candidate"]["value"][:120] if slot["head"] else None,
                    "not_a_fact": True,
                }))
    unresolved.sort(key=lambda pair: (-pair[0], pair[1]["topic"], pair[1]["id"]))
    result = {
        "ok": True, "command": "recall", "strategy": "lexical-v1",
        "matches": [], "matched": len(ranked), "omitted": len(ranked),
        "unresolved": [], "unresolved_omitted": len(unresolved),
    }
    for _, item in ranked:
        if len(result["matches"]) >= limit:
            break
        proposed = {**result, "matches": [*result["matches"], item],
                    "omitted": result["omitted"] - 1}
        if len(canonical(proposed)) + 1 <= budget_chars:
            result = proposed
    for _, item in unresolved:
        if len(result["unresolved"]) >= limit:
            break
        proposed = {**result, "unresolved": [*result["unresolved"], item],
                    "unresolved_omitted": result["unresolved_omitted"] - 1}
        if len(canonical(proposed)) + 1 <= budget_chars:
            result = proposed
    return result
