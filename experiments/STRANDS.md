# P2: Two-strand pairing for meaning-level damage (pre-registered 2026-11-02)

This section was written and committed **before** the detector or the evaluation existed. Results are appended below it without changing the hypotheses, thresholds or metrics.

## Motivation

Earlier experiments showed that `dna-v1` complementary redundancy is equivalent to a plain copy: the complement strand carries no information the primary strand lacks, so it can only undo byte damage, exactly like a backup.

DNA repair is useful for a different reason. The two strands can check each other locally, damage shows up as an unpaired position, and the intact strand is the template for repair. For LLM-agent memory, the damage that matters is usually not a flipped byte. It is **semantic drift inside the legitimate write path**: an extractor or a rewrite stores a wrong value, adds a modifier, or drops a negation. Such errors are written through `ingest`, so checksums and backups are recomputed and see nothing.

Every MemoryGene event already has two strands with **independent information**: the condensed `value` and the verbatim `source`. The hypothesis is that pairing them is where a DNA analogy can do real work.

## Hypotheses

- **H2a (detection):** a pairing check between `value` and `source` detects in-path semantic damage that byte-level protection (checksum + complement backup) cannot detect at all.
- **H2b (false alarms):** on legitimate extractions, the pairing check rarely flags anything. Legitimate means the gold labels and the values written by the independent held-out LLM extractor.
- **H2c (beyond the trivial):** the pairing check is better than the simplest possible baseline, exact substring containment (`value in source`), on at least one of the two measures without being worse on the other.

H2c can fail. If it does, the honest conclusion is that the useful part is "keep the verbatim evidence and check against it", which needs no DNA framing.

## Methods compared

- **M0 byte protection:** current `dna-v1` (SHA-256 + packed complement backup). Damaged values are written through `ingest`, then `verify()` runs.
- **M1 exact containment:** paired iff the normalized value is a substring of the normalized source.
- **M2 strand pairing:** paired iff (containment, or at least 0.5 of the value's cues — Chinese bigrams / words — appear in the source) **and** no negation marker precedes the value in the source. The negation markers are a fixed generic list (不再, 不喜欢, 不爱, 没那么, 讨厌, 戒了, 不是, no longer, not, don't), and the 0.5 threshold is the same as P1's value rule. Neither is tuned on this data.

## Data

- **Legitimate pairs:** gold write labels (value + verbatim text) from `nl_cases.json` and the held-out `cases.json`; and the held-out LLM's own written (value, source) pairs.
- **Damaged pairs:** five deterministic operators applied to each gold pair, each modelling a rewrite error:
  1. **substitute:** the value is replaced by another case's value that does not appear in this source;
  2. **embellish:** a fixed modifier is prepended ("蓝色", "进口", "小号", "野生", chosen in turn);
  3. **merge:** the value is concatenated with another case's value (two memories fused);
  4. **negation loss:** the source is rewritten as "我不再喜欢{value}了" while the value is kept as a positive fact;
  5. **truncate:** the last character is dropped (only for values with at least 3 characters). This is expected to be a blind spot, because a truncated value is still contained in the source.

## Metrics

- Detection rate per operator, for M0, M1 and M2.
- False-alarm rate on gold pairs and on held-out LLM pairs, for M1 and M2.
- All denominators are reported. There are no significance claims; the data is small, fictional and written by the same team.

---

## Results (appended after running; nothing above was changed)

Reproduce: `python experiments/strand_eval.py`. Raw numbers and false-alarm examples: [results/strands.json](results/strands.json). Code: [src/memorygene/strands.py](../src/memorygene/strands.py).

Detected damaged pairs (87 gold pairs; truncation applies to 33):

| Damage | M0 byte protection | M1 containment | M2 pre-registered pairing | M3 post-hoc strict |
| --- | --- | --- | --- | --- |
| substitute | 0 / 87 | 87 / 87 | 87 / 87 | 87 / 87 |
| embellish | 0 / 87 | 87 / 87 | **51 / 87** | 87 / 87 |
| merge | 0 / 87 | 87 / 87 | **23 / 87** | 87 / 87 |
| negation loss | 0 / 87 | **0 / 87** | 87 / 87 | 87 / 87 |
| truncate | 0 / 33 | 0 / 33 | 0 / 33 | 0 / 33 |

False alarms on legitimate pairs:

| Data | M1 containment | M2 pre-registered | M3 post-hoc strict |
| --- | --- | --- | --- |
| gold labels (87) | 0 | 1 | 0 |
| held-out LLM writes (28) | 0 | 0 | 0 |

### Verdict on the pre-registered hypotheses

- **H2a supported.** Byte protection detected 0 of 381 in-path semantic damages. This is by construction: damage written through `ingest` gets a fresh checksum and backup. Any pairing rule detected most of them.
- **H2b supported** for these data: 1/87 and 0/28 false alarms for M2.
- **H2c failed.** M2 was worse than plain containment on embellish (51 vs 87) and merge (23 vs 87) and had one more false alarm. Its only gain was negation loss. The tolerance for partial cues was meant to accept paraphrased values, but the legitimate values here were almost always verbatim substrings, so the tolerance only cost detection. The single M2 false alarm is a correction sentence ("不是玫瑰，是百合"), where the negation belongs to the old value.

### Post-hoc rule (exploratory)

M3 = containment plus a negation check limited to the value's own clause. It was **chosen after seeing the results above** and is now the default in `strands.pairing`. On these data it detects four of five damage types with no false alarms. It still needs fresh data, for three reasons:

- the negation-loss operator inserts "不再喜欢", which is itself in the marker list, so that row is partly true by construction;
- truncation remains invisible to every method, because a truncated value is still contained in its evidence;
- containment will reject legitimate paraphrased or normalised values (dates, numbers, synonyms) that these datasets happen not to contain.

### Observation on a real store

On the developer's own local store (4 stored versions in 3 slots), 3 versions do not pair. In each, the agent saved a long summary as the value while quoting a much shorter user sentence as the source, so the value contains details absent from the evidence (one includes a technical figure the user never stated). Under the project's rule that memory must not contain unsupported user information, flagging these is correct. In practice it also means `unpaired_value` advice will be frequent unless agents quote the full supporting evidence. This is one store, reported as an observation, not a measurement.

### What this means for the DNA question

- The complement *encoding* (`dna-v1`) contributes nothing measurable, as before.
- What helps is a second strand carrying **independent information** (verbatim evidence) plus a local pairing check: damage shows up as an unpaired value, legitimate updates bring their own evidence, and repair means re-reading the template with the user, never guessing.
- Whether to call this "DNA-inspired" is a framing choice. Computationally it is evidence grounding. We keep the analogy only as a description of the structure — two strands, local mismatch detection, the template strand used for repair — not as a claim of biological mechanism.
