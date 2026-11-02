"""Structured-policy / byte-recovery smoke experiments. No model or network calls."""

import argparse
import json
import platform
import random
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from memorygene import Candidate, MemoryStore, __version__
from memorygene.codec import IntegrityError, checksum, packed_complement, recover

NOW = "2026-10-24T10:00:00Z"


def policies(cases):
    metrics = []
    trace = []
    for mode in ("overwrite", "append_all", "rules_plain", "rules_complement"):
        correct_current = correct_history = false_activations = uncertain_writes = 0
        uncertain_total = transitions = 0
        with MemoryStore(
            index="plain" if mode == "rules_plain" else "complement"
        ) as store:
            for case in cases:
                values = []
                for i, turn in enumerate(case["turns"]):
                    c = Candidate(**turn)
                    if mode.startswith("rules"):
                        event = store.ingest(c, case["id"] + ":" + str(i), now=NOW)
                        active = event["status"] == "confirmed"
                        status = event["status"]
                    else:
                        active, status = True, "confirmed"
                        values.append(c.value)
                    expected_active = case["expected_statuses"][i] == "confirmed"
                    false_activations += active and not expected_active
                    uncertain_total += c.certainty != "explicit"
                    uncertain_writes += active and c.certainty != "explicit"
                    transitions += 1
                    trace.append(
                        dict(
                            mode=mode,
                            case=case["id"],
                            turn=i,
                            expected=case["expected_statuses"][i],
                            actual=status,
                        )
                    )
                if mode.startswith("rules"):
                    current = store.current(
                        "fixture", "fictional", case["topic"], now=NOW
                    )
                    current_value = current["candidate"]["value"] if current else None
                    history = [
                        e["candidate"]["value"]
                        for e in store.history(
                            "fixture", "fictional", case["topic"], now=NOW
                        )
                        if e["status"] == "confirmed"
                    ]
                else:
                    current_value = values[-1] if values else None
                    history = values[-1:] if mode == "overwrite" else values
                correct_current += current_value == case["expected_current"]
                correct_history += history == case["expected_history"]
        metrics.append(
            dict(
                mode=mode,
                scenarios=len(cases),
                transitions=transitions,
                current_correct=correct_current,
                current_accuracy=correct_current / len(cases),
                history_correct=correct_history,
                history_accuracy=correct_history / len(cases),
                false_activations=false_activations,
                uncertain_writes=uncertain_writes,
                uncertain_total=uncertain_total,
            )
        )
    return metrics, trace


def protection_experiment(seed, n=100):
    rng = random.Random(seed)
    payloads = [
        bytes(rng.randrange(256) for _ in range(rng.randrange(80, 300)))
        for _ in range(n)
    ]
    rows = []
    for mode in ("none", "copy", "complement"):
        for damage in (
            "healthy",
            "primary_loss",
            "primary_bitflip",
            "backup_loss",
            "both_loss",
            "checksum_loss",
        ):
            successes = 0
            elapsed = []
            for data in payloads:
                backup = (
                    None
                    if mode == "none"
                    else (data if mode == "copy" else packed_complement(data))
                )
                primary, expected = data, checksum(data)
                if damage in ("primary_loss", "both_loss"):
                    primary = b""
                if damage == "primary_bitflip":
                    primary = bytes([data[0] ^ 1]) + data[1:]
                if damage in ("backup_loss", "both_loss"):
                    backup = None
                if damage == "checksum_loss":
                    expected = "0" * 64
                start = time.perf_counter_ns()
                try:
                    restored = recover(primary, backup, expected, mode)
                    successes += restored == data
                except IntegrityError:
                    pass
                elapsed.append(time.perf_counter_ns() - start)
            primary_bytes = sum(map(len, payloads))
            rows.append(
                dict(
                    mode=mode,
                    damage=damage,
                    trials=n,
                    recovered=successes,
                    recovery_rate=successes / n,
                    primary_bytes=primary_bytes,
                    redundancy_bytes=0 if mode == "none" else primary_bytes,
                    checksum_ascii_bytes=64 * n,
                    median_recovery_ns=statistics.median(elapsed),
                )
            )
    return rows


def index_experiment(n=300, repeats=7):
    rows = []
    with tempfile.TemporaryDirectory() as d:
        for mode in ("plain", "complement"):
            path = Path(d) / (mode + ".db")
            with MemoryStore(path, index=mode, protection="none") as store:
                for i in range(n):
                    c = Candidate(
                        "bench",
                        "fictional",
                        f"preference.topic.{i}",
                        str(i),
                        "synthetic evidence",
                        NOW,
                    )
                    store.ingest(c, str(i), now=NOW)
                trials = []
                correct = 0
                for _ in range(repeats):
                    start = time.perf_counter_ns()
                    for i in range(n):
                        e = store.current(
                            "bench", "fictional", f"preference.topic.{i}", now=NOW
                        )
                        correct += e["candidate"]["value"] == str(i)
                    trials.append((time.perf_counter_ns() - start) / n)
                # Per-row bytes for actual routing keys; database bytes include all tables and indices.
                key_bytes = store.db.execute(
                    "SELECT sum(length(cast(route as blob))) FROM events"
                ).fetchone()[0]
            rows.append(
                dict(
                    mode=mode,
                    records=n,
                    repeats=repeats,
                    correct=correct,
                    queries=n * repeats,
                    median_query_ns=statistics.median(trials),
                    per_repeat_ns=trials,
                    event_route_bytes=key_bytes,
                    database_bytes=path.stat().st_size,
                )
            )
    return rows


def plot(result, out):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    modes = result["policies"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3), layout="constrained")
    labels = ["Overwrite", "Append all", "Rules / plain", "Rules / complement"]
    axes[0].barh(
        labels,
        [m["current_accuracy"] * 100 for m in modes],
        color=["#999999", "#666666", "#317873", "#1d4f4b"],
    )
    axes[0].set(
        xlim=(0, 105),
        xlabel="Current-state accuracy (%)",
        title="24 hand-labelled synthetic scenarios",
    )
    axes[1].barh(
        labels,
        [m["history_accuracy"] * 100 for m in modes],
        color=["#999999", "#666666", "#317873", "#1d4f4b"],
    )
    axes[1].set(
        xlim=(0, 105),
        xlabel="Exact confirmed-history accuracy (%)",
        title="Structured input; no NLP evaluation",
    )
    fig.savefig(out / "policy.png", dpi=180)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3), layout="constrained")
    damage = [
        "primary_loss",
        "primary_bitflip",
        "backup_loss",
        "both_loss",
        "checksum_loss",
    ]
    x = list(range(len(damage)))
    for offset, mode, color in [
        (-0.24, "none", "#999999"),
        (0, "copy", "#317873"),
        (0.24, "complement", "#1d4f4b"),
    ]:
        vals = [
            next(
                r["recovery_rate"] * 100
                for r in result["protection"]
                if r["mode"] == mode and r["damage"] == k
            )
            for k in damage
        ]
        axes[0].bar([i + offset for i in x], vals, width=0.24, label=mode, color=color)
    axes[0].set_xticks(
        x,
        [
            "Primary\nloss",
            "Primary\nbitflip",
            "Backup\nloss",
            "Both\nloss",
            "Digest\nloss",
        ],
    )
    axes[0].set(
        ylim=(0, 110),
        ylabel="Verified recovery (%)",
        title="100 paired payloads per condition",
    )
    axes[0].legend(fontsize=8)
    idx = result["index"]
    axes[1].bar(
        ["Plain", "Complement"],
        [r["event_route_bytes"] / 1024 for r in idx],
        color=["#317873", "#1d4f4b"],
    )
    axes[1].set(
        ylabel="Total event routing keys (KiB)",
        title="Reversible ASCII bases cost 4x bytes",
    )
    fig.savefig(out / "mechanism.png", dpi=180)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("experiments/results"))
    p.add_argument("--seed", type=int, default=20261024)
    p.add_argument("--plots", action="store_true")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    cases = json.loads((Path(__file__).with_name("scenarios.json")).read_text())
    metrics, trace = policies(cases)
    result = dict(
        version=__version__,
        generated_at=datetime.now(timezone.utc).isoformat(),
        seed=a.seed,
        python=sys.version,
        platform=platform.platform(),
        evidence_clock=NOW,
        policies=metrics,
        protection=protection_experiment(a.seed),
        index=index_experiment(),
        limitations=[
            "Hand-labelled development fixtures, not a held-out or natural-language benchmark.",
            "Policies receive certainty/intent/importance labels; extractor errors are excluded.",
            "Exact-key retrieval only; semantic relevance and proactive recall are not evaluated.",
            "Recovery covers payload bytes, not SQLite page/index/head-pointer destruction.",
            "Timings are descriptive on one local machine; execution order is fixed.",
        ],
    )
    (a.out / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    (a.out / "trace.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2) + "\n"
    )
    if a.plots:
        plot(result, a.out)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
