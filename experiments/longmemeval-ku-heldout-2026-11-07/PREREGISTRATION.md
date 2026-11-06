# Pre-registration: LongMemEval knowledge-update held-out test (2026-11-07)

Written and committed before any model call for this test. Results will be added in a separate REPORT.md without changing this file.

## Why

The `latest` update mode was designed after seeing the first 20 knowledge-update questions, so its 16/20 on them is not an independent test. This run uses the 58 remaining knowledge-update questions, none of which has been looked at.

## Fixed in advance

- **Data:** `longmemeval_oracle.json` from `longmemeval-cleaned` (sha256 `821a2034d219ab45…`), the same file as before.
- **Sample:** every `knowledge-update` question in `question_id` order after the first 20, i.e. 58 questions.
- **Method:** identical to [../longmemeval-ku-2026-11-02](../longmemeval-ku-2026-11-02): the same [prompt](../longmemeval-ku-2026-11-02/prompt.md), one DeepSeek Harness headless call per question (`deepseek-flash`), the same parsing, evaluation clock, policies and scoring rules (current / history / abstention questions, automatic matching).
- **Primary comparison:** total correct for `memorygene_latest` versus `latest_explicit`, the strongest baseline so far.

## Predictions

1. `memorygene_latest` scores at least as high as `latest_explicit`.
2. `memorygene` (default mode, no confirmation) scores no higher than `memorygene_latest`.
3. As before, most errors shared by all policies come from extraction rather than from the update policy.

A failed prediction will be reported as such. With 58 questions, a difference of one or two questions is not meaningful.
