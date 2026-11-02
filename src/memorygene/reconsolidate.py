"""Read-only reconsolidation support: locate related memories, open evidence, advice.

Reactivating a memory is the moment it can be revised. Here that moment is a
write or a question: before the agent stores or answers something, it can see
which existing slots look like the same attribute, which earlier evidence is
still unresolved, and whether the user should be asked.

Nothing in this module writes. The state machine in ``core.MemoryStore.ingest``
stays the only path that changes memory, so advice can never confirm a fact on
its own. Matching is lexical (topic tokens, Chinese bigrams, words), weighted
by how rare a term is among the subject's own slots; it is not semantic search.
"""

import math
import re
import unicodedata

from .core import Candidate, instant, now_string
from .recall import terms
from .strands import pairing

_TOPIC_SPLIT = re.compile(r"[^a-z0-9]+")


def topic_tokens(topic):
    return {t for t in _TOPIC_SPLIT.split(topic.lower()) if t}


def attribute(topic):
    """The last token of a topic name: ``preference.liked_flower`` -> ``flower``."""
    parts = [t for t in _TOPIC_SPLIT.split(topic.lower()) if t]
    return parts[-1] if parts else ""


def values_related(new, old):
    """Same value, one contains the other, or at least half of the shorter
    value's cues are shared. A few shared words inside long free-text values
    ("本地", "模型") are not enough."""
    a = unicodedata.normalize("NFKC", new).casefold().strip()
    b = unicodedata.normalize("NFKC", old).casefold().strip()
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta, tb = terms(a), terms(b)
    return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def cues(topic, values, sources):
    """Recognition cues of a slot or a new statement, tagged by origin."""
    out = {("t", t) for t in topic_tokens(topic)}
    for text in values:
        out |= {("v", t) for t in terms(text)} if text.strip() else set()
    for text in sources:
        out |= {("s", t) for t in terms(text)} if text.strip() else set()
    return out


def _bare(tagged):
    return {term for _, term in tagged}


def slots(store, namespace, subject, *, now=None, visible_session=""):
    """Every visible slot with its live head and its full evidence list."""
    if not isinstance(visible_session, str):
        raise ValueError("visible_session must be text; empty means persistent only")
    namespace = unicodedata.normalize("NFC", namespace)
    subject = unicodedata.normalize("NFC", subject)
    clock = instant(now or now_string())
    out = []
    for row in store.db.execute("SELECT DISTINCT route FROM events ORDER BY route"):
        ns, subj, topic, scope, session = store._route_parts(row["route"])
        if ns != namespace or subj != subject:
            continue
        if scope == "session" and (not visible_session or session != visible_session):
            continue
        events = [
            store._read(r)
            for r in store.db.execute(
                "SELECT * FROM events WHERE route=? ORDER BY seq", (row["route"],)
            )
        ]
        head = store._head(row["route"])
        live = head if head and store._live(head, clock) else None
        out.append({
            "topic": topic, "scope": scope, "session": session,
            "head": live, "events": events,
        })
    return out


def open_evidence(slot, *, now=None):
    """Pending/conflict evidence that nothing later has settled.

    Evidence is settled when a later event names it in ``resolves``, when any
    later confirmed event re-states the slot explicitly, when it equals the
    live current value, or when it has expired.
    """
    clock = instant(now or now_string())
    events = slot["events"]
    resolved = {e["resolves"] for e in events if e.get("resolves")}
    current = slot["head"]["candidate"]["value"] if slot["head"] else None
    out = []
    for i, event in enumerate(events):
        if event["status"] not in {"pending", "conflict"} or event["id"] in resolved:
            continue
        expiry = event["candidate"].get("expires_at")
        if expiry and instant(expiry) <= clock:
            continue
        if event["candidate"]["value"] == current:
            continue
        if any(e["status"] == "confirmed" for e in events[i + 1:]):
            continue
        out.append(event)
    return out


def _weights(all_slot_cues):
    """Inverse slot frequency: a term on every slot ('preference') says little."""
    n = len(all_slot_cues)
    df = {}
    for slot_cues in all_slot_cues:
        for term in _bare(slot_cues):
            df[term] = df.get(term, 0) + 1
    return lambda term: math.log((n + 1) / (df.get(term, 0) + 0.5))


def locate(store, namespace, subject, topic, value, source, *, now=None,
           visible_session="", limit=5, use=("t", "v", "s")):
    """Rank existing slots by how likely they hold the same attribute.

    ``use`` selects cue origins and exists for ablations: ("t",) is topic-name
    matching only. Each match reports whether the slot's live value equals the
    new value (``match``), differs (``mismatch``) or is absent (``empty``).
    """
    found = slots(store, namespace, subject, now=now, visible_session=visible_session)
    probe = {c for c in cues(topic, [value], [source]) if c[0] in use}
    slot_cues = [
        {c for c in cues(
            s["topic"],
            [e["candidate"]["value"] for e in s["events"]],
            [e["candidate"]["source"] for e in s["events"]],
        ) if c[0] in use}
        for s in found
    ]
    weight = _weights(slot_cues + [probe])
    probe_t = _bare({c for c in probe if c[0] == "t"})
    probe_c = _bare({c for c in probe if c[0] != "t"})
    ranked = []
    for slot, sc in zip(found, slot_cues):
        slot_t = _bare({c for c in sc if c[0] == "t"})
        slot_c = _bare({c for c in sc if c[0] != "t"})
        shared = (probe_t & slot_t) | (probe_c & slot_c)
        if not shared:
            continue
        # Topic names are short, so Dice compares them symmetrically. Content
        # (values, verbatim sources) grows with every piece of evidence, so the
        # overlap coefficient keeps a long slot history from diluting a match.
        mass = sum(weight(t) for t in probe_t) + sum(weight(t) for t in slot_t)
        s_topic = 2 * sum(weight(t) for t in probe_t & slot_t) / mass if mass else 0.0
        small = min(sum(weight(t) for t in probe_c), sum(weight(t) for t in slot_c))
        s_content = sum(weight(t) for t in probe_c & slot_c) / small if small else 0.0
        parts = [x for x, on in ((s_topic, "t" in use), (s_content, "v" in use or "s" in use)) if on]
        score = sum(parts) / len(parts)
        # Sharing only category words ("preference", "favorite") is weak
        # evidence. A slot is anchored when the attribute word of either topic
        # appears in the other, or when the values are clearly related.
        anchored = (
            ("t" in use and (attribute(topic) in slot_t or attribute(slot["topic"]) in probe_t))
            or ("v" in use and any(values_related(value, e["candidate"]["value"])
                                   for e in slot["events"]))
        )
        head = slot["head"]
        ranked.append({
            "topic": slot["topic"], "scope": slot["scope"],
            "same_topic": slot["topic"] == topic,
            "score": round(score, 4),
            "anchored": anchored,
            "relation": (
                "empty" if head is None
                else "match" if head["candidate"]["value"] == value
                else "mismatch"
            ),
            "current": head["candidate"]["value"] if head else None,
            "current_id": head["id"] if head else None,
            "open_evidence": [e["id"] for e in open_evidence(slot, now=now)],
            "shared_cues": sorted(shared)[:8],
        })
    ranked.sort(key=lambda r: (-r["same_topic"], -r["anchored"], -r["score"], r["topic"]))
    return ranked[:limit]


def advise(store, candidate: Candidate, result, *, now=None, visible_session=""):
    """Advice for the agent after an ingest; empty when nothing needs saying.

    Advice kinds (all suggestions, never actions):

    * ``confirm_change``: an explicit, newer statement disagrees with the
      current value and was held as ``conflict`` because no change was stated.
    * ``possible_same_slot``: a value was confirmed under a topic that had no
      prior value while another live slot is anchored to it (same attribute
      word or shared value cues), i.e. the topic name may have drifted.
    * ``repeated_uncertain``: the same uncertain value has now been heard at
      least twice, at different times; the user may be asked once.
    * ``auto_updated``: in ``update="latest"`` mode an unmarked assertion
      replaced the previous value; the agent may mention the change.
    * ``unpaired_value``: the value does not pair with its own verbatim source
      (content not found in the evidence, or negated there); see strands.py.
    """
    status = result["status"]
    if status in {"discarded", "rejected_sensitive", "expired", "duplicate"}:
        return []
    related = locate(
        store, candidate.namespace, candidate.subject, candidate.topic,
        candidate.value, candidate.source, now=now,
        visible_session=visible_session,
    )
    same = next((r for r in related if r["same_topic"] and r["scope"] == candidate.scope), None)
    advice = []
    pair = pairing(candidate.value, candidate.source)
    if not pair["paired"]:
        advice.append({
            "kind": "unpaired_value", "topic": candidate.topic,
            "coverage": pair["coverage"], "negated": pair["negated"],
            "unsupported": pair["unsupported"], "evidence_id": result["id"],
            "next": "the stored value says more than (or the opposite of) the quoted "
                    "evidence; quote the user's words that support it, or ask the user",
        })
    if (status == "conflict" and candidate.certainty == "explicit" and same
            and same["current"] is not None):
        head = store.current(candidate.namespace, candidate.subject, candidate.topic,
                             scope=candidate.scope, session=candidate.session, now=now)
        if head and instant(candidate.at) >= instant(head["candidate"]["at"]):
            advice.append({
                "kind": "confirm_change", "topic": candidate.topic,
                "current": same["current"], "proposed": candidate.value,
                "evidence_id": result["id"],
                "next": "ask whether this is a change; if the user confirms, "
                        "remember again with --intent change --resolves <evidence_id>",
            })
    if status == "confirmed" and result.get("policy") == "latest":
        advice.append({
            "kind": "auto_updated", "topic": candidate.topic,
            "previous_id": result.get("previous_id"), "current": candidate.value,
            "next": "the value was replaced without an explicit change; if it comes up, "
                    "mention the update so the user can correct it",
        })
    if status == "confirmed" and result.get("previous_id") is None:
        for other in related:
            if other["same_topic"] or other["current"] is None:
                continue
            if other["anchored"]:
                advice.append({
                    "kind": "possible_same_slot", "topic": candidate.topic,
                    "existing_topic": other["topic"], "existing_value": other["current"],
                    "score": other["score"], "relation": other["relation"],
                    "next": "if both topics mean the same attribute, keep one topic: "
                            "forget the new one and remember under the existing topic",
                })
                break
    if status == "pending" and same:
        slot_events = store.history(candidate.namespace, candidate.subject, candidate.topic,
                                    scope=candidate.scope, session=candidate.session, now=now)
        open_ids = set(same["open_evidence"])
        times = {e["candidate"]["at"] for e in slot_events
                 if e["id"] in open_ids and e["candidate"]["value"] == candidate.value}
        if len(times) >= 2:
            advice.append({
                "kind": "repeated_uncertain", "topic": candidate.topic,
                "value": candidate.value, "times_heard": len(times),
                "next": "if relevant to the conversation, ask the user once whether "
                        "this should become their current value",
            })
    return advice


def review(store, namespace, subject, *, now=None, visible_session=""):
    """Self-check: unresolved evidence, duplicate-looking slots, unpaired values."""
    found = slots(store, namespace, subject, now=now, visible_session=visible_session)
    unresolved = []
    for slot in found:
        for event in open_evidence(slot, now=now):
            c = event["candidate"]
            unresolved.append({
                "topic": slot["topic"], "scope": slot["scope"], "evidence_id": event["id"],
                "status": event["status"], "value": c["value"], "source": c["source"],
                "current": slot["head"]["candidate"]["value"] if slot["head"] else None,
            })
    unpaired = []
    for slot in found:
        if slot["head"]:
            c = slot["head"]["candidate"]
            pair = pairing(c["value"], c["source"])
            if not pair["paired"]:
                unpaired.append({"topic": slot["topic"], "scope": slot["scope"],
                                 "evidence_id": slot["head"]["id"],
                                 "coverage": pair["coverage"], "negated": pair["negated"]})
    duplicates = []
    live = [s for s in found if s["head"]]
    for i, slot in enumerate(live):
        c = slot["head"]["candidate"]
        for other in locate(store, namespace, subject, slot["topic"], c["value"], c["source"],
                            now=now, visible_session=visible_session, limit=20):
            if other["same_topic"] or not other["anchored"]:
                continue
            pair = tuple(sorted((slot["topic"], other["topic"])))
            if pair not in {tuple(d["topics"]) for d in duplicates}:
                duplicates.append({"topics": list(pair), "score": other["score"],
                                   "values": sorted({c["value"], other["current"] or ""})})
    return {
        "ok": True, "command": "review",
        "unresolved": unresolved, "possible_duplicate_slots": duplicates,
        "unpaired_current": unpaired,
        "slots": len(found),
    }
