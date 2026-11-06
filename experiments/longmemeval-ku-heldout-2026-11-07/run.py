"""Held-out test on the 58 LongMemEval knowledge-update questions not used so far.

Pre-registered before any model call (see PREREGISTRATION.md):
  * Sample: all "knowledge-update" questions in question_id order after the
    first 20, which were used in experiments/longmemeval-ku-2026-11-02 and
    while designing the `latest` update mode. None of these 58 was seen.
  * Everything else is reused unchanged from that experiment: the extraction
    prompt, one DeepSeek Harness headless call per question, candidate
    parsing, the evaluation clock, the policies and the scoring rules.

Usage:
  python experiments/longmemeval-ku-heldout-2026-11-07/run.py extract --data PATH
  python experiments/longmemeval-ku-heldout-2026-11-07/run.py score --data PATH
"""

import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_PATH = HERE.parent / "longmemeval-ku-2026-11-02" / "run.py"
SPEC = importlib.util.spec_from_file_location("lme_ku_base", BASE_PATH)
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)

USED = 20


def heldout(data_path):
    data = json.loads(Path(data_path).read_text("utf-8"))
    ku = sorted((x for x in data if x["question_type"] == "knowledge-update"),
                key=lambda x: x["question_id"])
    return ku[USED:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["extract", "score"])
    parser.add_argument("--data", required=True)
    args = parser.parse_args()
    items = heldout(args.data)
    if args.step == "extract":
        base.extract(items, raw=HERE / "raw")
    else:
        base.score(items, raw=HERE / "raw", out=HERE / "results.json")


if __name__ == "__main__":
    main()
