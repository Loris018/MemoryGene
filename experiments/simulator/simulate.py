"""Scenario simulator: fictional user timelines with ground truth by construction.

Hand-written dialogue sets are small, slow to build, and labelled by the same
people who write the rules. This simulator instead samples a fictional user's
timeline of events (stating a preference, changing it with or without saying
so, hesitating, mentioning someone else's preference, retracting, ...) and
derives the correct memory state after every event from the event semantics
alone. MemoryGene's code is never consulted when computing the gold state.

Each event is rendered into one utterance from template banks (Chinese and
English). Templates are deterministic and free; they are less varied than
real speech, so results on them are an upper bound for rule-based extraction.
An LLM paraphrasing step can be added later without changing the gold.

Two conventions are recorded for an unmarked new value ("I live in Beijing"
after "I live in Shanghai"): `confirm` keeps the old value until the user
confirms, `latest` takes the new one. Every other event type has a single
gold outcome. A retraction ("I don't like roses any more") clears the
current value in both conventions.

Usage: python experiments/simulator/simulate.py --n 300 --seed 7 --out FILE
"""

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Attribute frames. `kind` selects the template family; values deliberately
# include items outside the rule-based extractor's lexicon.
ATTRIBUTES = {
    "preference.favorite_flower": {
        "kind": "like", "zh": "花", "en": "flower",
        "values": ["玫瑰", "百合", "栀子花", "郁金香", "向日葵", "桔梗", "绣球花", "铃兰"],
        "values_en": ["roses", "lilies", "tulips", "sunflowers", "orchids", "peonies"],
    },
    "preference.favorite_drink": {
        "kind": "like", "zh": "饮品", "en": "drink",
        "values": ["乌龙茶", "咖啡", "柠檬水", "热可可", "茉莉花茶", "椰子水", "豆浆"],
        "values_en": ["oolong tea", "coffee", "lemonade", "hot chocolate", "green tea"],
    },
    "preference.favorite_food": {
        "kind": "like", "zh": "食物", "en": "food",
        "values": ["火锅", "拉面", "饺子", "寿司", "煲仔饭", "肠粉", "烤鸭"],
        "values_en": ["hot pot", "ramen", "dumplings", "sushi", "pizza", "tacos"],
    },
    "preference.favorite_color": {
        "kind": "like", "zh": "颜色", "en": "colour",
        "values": ["蓝色", "绿色", "紫色", "橙色", "米白色", "墨绿色"],
        "values_en": ["blue", "green", "purple", "orange", "teal"],
    },
    "preference.favorite_sport": {
        "kind": "like", "zh": "运动", "en": "sport",
        "values": ["羽毛球", "游泳", "跑步", "攀岩", "乒乓球", "骑行"],
        "values_en": ["badminton", "swimming", "running", "climbing", "cycling"],
    },
    "profile.city": {
        "kind": "live", "zh": "城市", "en": "city",
        "values": ["上海", "北京", "杭州", "成都", "深圳", "苏州", "厦门"],
        "values_en": ["Shanghai", "Beijing", "Hangzhou", "Chengdu", "Shenzhen", "Lisbon"],
    },
}

TEMPLATES = {
    "zh": {
        "like": {
            "assert": ["我最喜欢{v}。", "我最喜欢的{noun}是{v}。", "说起{noun}，我最爱{v}。"],
            "change_marked": ["现在最喜欢{v}了。", "我改主意了，现在最喜欢{v}。",
                              "最近换口味了，现在最喜欢{v}。"],
            "correct": ["我刚才说错了，其实最喜欢{v}。", "更正一下，我最喜欢的是{v}。"],
            "hesitate": ["可能更喜欢{v}吧，还不太确定。", "好像{v}也不错，说不定更喜欢。"],
            "supplement": ["{v}也挺好的。", "我也喜欢{v}。"],
            "repeat": ["我还是最喜欢{v}。", "最喜欢的还是{v}。"],
            "third_party": ["我妈妈最喜欢{v}。", "我朋友最喜欢{v}。", "我室友最爱{v}。"],
            "mention": ["今天路过一家店，看到很多{v}。", "刚刚刷到一个讲{v}的视频。"],
            "retract": ["我不再喜欢{cur}了。", "其实我现在没那么喜欢{cur}了。"],
        },
        "live": {
            "assert": ["我住在{v}。", "我现在住在{v}。"],
            "change_marked": ["我搬到{v}了。", "我已经搬去{v}住了。"],
            "correct": ["我刚才说错了，我住在{v}。", "更正一下，我住的城市是{v}。"],
            "hesitate": ["我可能会搬去{v}，还没定。", "也许明年住到{v}吧，不确定。"],
            "repeat": ["我还住在{v}。"],
            "third_party": ["我哥哥住在{v}。", "我朋友住在{v}。"],
            "mention": ["上周去{v}出差了。", "最近在看{v}的旅游攻略。"],
            "retract": ["我已经不住在{cur}了。"],
        },
    },
    "en": {
        "like": {
            "assert": ["I like {v} best.", "My favourite {noun} is {v}.", "When it comes to {noun}, I love {v} the most."],
            "change_marked": ["These days my favourite is {v}.", "I've changed my mind, now I like {v} best.",
                              "My taste changed, {v} is my favourite now."],
            "correct": ["Sorry, I misspoke, my favourite is actually {v}.", "Correction: my favourite is {v}."],
            "hesitate": ["Maybe I like {v} more, not sure yet.", "I think {v} might be my favourite, hard to say."],
            "supplement": ["{v} is nice too.", "I also like {v}."],
            "repeat": ["I still like {v} best.", "{v} is still my favourite."],
            "third_party": ["My mum's favourite is {v}.", "My friend likes {v} best."],
            "mention": ["I walked past a shop full of {v} today.", "I just watched a video about {v}."],
            "retract": ["I don't like {cur} any more.", "Honestly, I'm not into {cur} these days."],
        },
        "live": {
            "assert": ["I live in {v}.", "I'm based in {v}."],
            "change_marked": ["I've moved to {v}.", "I just relocated to {v}."],
            "correct": ["Sorry, I misspoke, I live in {v}.", "Correction: I live in {v}."],
            "hesitate": ["I might move to {v}, nothing is decided.", "Maybe I'll live in {v} next year."],
            "repeat": ["I'm still living in {v}."],
            "third_party": ["My brother lives in {v}.", "A friend of mine lives in {v}."],
            "mention": ["I was in {v} for work last week.", "I'm reading travel guides about {v}."],
            "retract": ["I don't live in {cur} any more."],
        },
    },
}

# Follow-up event types and their sampling weights. `change_unmarked` reuses
# the `assert` templates: the words do not say that anything changed.
FOLLOW_UPS = {
    "change_marked": 3, "change_unmarked": 3, "correct": 1, "hesitate": 3,
    "supplement": 2, "repeat": 2, "third_party": 2, "mention": 2, "retract": 1,
}
# The labels a perfect extractor would produce for each event type.
ORACLE = {
    "assert": {"decision": "write", "certainty": "explicit", "intent": "assert"},
    "change_marked": {"decision": "write", "certainty": "explicit", "intent": "change"},
    "change_unmarked": {"decision": "write", "certainty": "explicit", "intent": "assert"},
    "correct": {"decision": "write", "certainty": "explicit", "intent": "correct"},
    "hesitate": {"decision": "write", "certainty": "uncertain", "intent": "assert"},
    "supplement": {"decision": "write", "certainty": "explicit", "intent": "supplement"},
    "repeat": {"decision": "write", "certainty": "explicit", "intent": "assert"},
    "third_party": {"decision": "skip"},
    "mention": {"decision": "skip"},
    "retract": {"decision": "write", "certainty": "explicit", "intent": "retract"},
}


def gold_step(state, event, convention):
    """Apply one event's meaning to the gold state (current value + history)."""
    current, history = state
    kind, value = event["type"], event["value"]
    if kind in ("assert", "change_marked", "correct") or (
            kind == "change_unmarked" and convention == "latest"):
        if value != current:
            history = history + [value]
        return value, history
    if kind == "retract":
        return None, history
    return current, history


def sample_timeline(rng, lang, index):
    topic = rng.choice(sorted(ATTRIBUTES))
    frame = ATTRIBUTES[topic]
    if frame["kind"] == "live":
        types = {k: w for k, w in FOLLOW_UPS.items() if k != "supplement"}
    else:
        types = dict(FOLLOW_UPS)
    pool = frame["values"] if lang == "zh" else frame["values_en"]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=rng.randrange(200))
    current = rng.choice(pool)
    possible = {current}  # current value under either convention
    events = [{"type": "assert", "value": current}]
    for _ in range(rng.randint(1, 4)):
        allowed = dict(types)
        if len(possible) > 1:
            # After an unmarked change the two conventions disagree about the
            # current value, so events that refer to it would be ambiguous.
            for k in ("repeat", "retract", "change_unmarked"):
                allowed.pop(k, None)
        kind = rng.choices(sorted(allowed), weights=[allowed[k] for k in sorted(allowed)])[0]
        if current is None and kind in ("repeat", "retract", "change_unmarked"):
            kind = "assert"
        if kind in ("repeat", "retract"):
            value = current
        else:
            value = rng.choice([v for v in pool if v not in possible])
        events.append({"type": kind, "value": value})
        if kind in ("assert", "change_marked", "correct"):
            current, possible = value, {value}
        elif kind == "retract":
            current, possible = None, {None}
        elif kind == "change_unmarked":
            possible = {current, value}
    when = start
    for event in events:
        when += timedelta(days=rng.randint(1, 20), hours=rng.randint(0, 12))
        event["at"] = when.isoformat()
        family = TEMPLATES[lang][frame["kind"]]
        bank = family["assert" if event["type"] == "change_unmarked" else event["type"]]
        noun = frame[lang]
        text = rng.choice(bank).format(v=event["value"], cur=event["value"], noun=noun)
        event["text"] = text[0].upper() + text[1:] if lang == "en" else text
        event["oracle"] = {**ORACLE[event["type"]], "topic": topic, "value": event["value"]}
    gold = {}
    for convention in ("confirm", "latest"):
        state = (None, [])
        for event in events:
            state = gold_step(state, event, convention)
        gold[convention] = {"current": state[0], "history": state[1]}
    now = (when + timedelta(days=1)).isoformat()
    return {"id": f"sim-{lang}-{index:04d}", "lang": lang, "topic": topic,
            "now": now, "events": events, "gold": gold}


def generate(n, seed, langs=("zh", "en")):
    rng = random.Random(seed)
    return [sample_timeline(rng, langs[i % len(langs)], i) for i in range(n)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = generate(args.n, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(data)} timelines to {args.out}")


if __name__ == "__main__":
    main()
