"""Two-strand pairing: check a stored value against its verbatim evidence.

Every event carries two strands with independent information: the condensed
``value`` and the user's verbatim ``source``. Byte protection (checksum,
copy or complement backup) cannot tell when the value itself was written
wrongly through the legitimate path, because it protects whatever was written.
Pairing asks a different question: does the value still pair with the
evidence it claims to come from? An unpaired value is flagged, never repaired
automatically; the caller re-reads the source with the user.

Two rules exist (see experiments/STRANDS.md):

* ``preregistered``: paired iff the value is contained in the source or at
  least half of its cues occur in it, and no negation marker appears anywhere
  before the value. Fixed before the evaluation; it lost to plain containment
  on two damage types (hypothesis H2c failed).
* ``strict`` (default): paired iff the value is contained in the source and no
  negation marker appears in the same clause before it. Chosen *after* seeing
  the pre-registered results; it still needs validation on fresh data.
"""

import re
import unicodedata

from .recall import terms

PAIR_THRESHOLD = 0.5
NEGATIONS = ("不再", "不喜欢", "不爱", "没那么", "讨厌", "戒了", "不是",
             "no longer", "not ", "don't", "do not")
_CLAUSE_BREAK = re.compile(r"[，,。.！!？?；;：:\n]")


def _norm(text):
    return unicodedata.normalize("NFKC", text).casefold().strip()


def pairing(value, source, *, mode="strict"):
    """Return how ``value`` pairs with ``source``.

    ``coverage`` is 1.0 for containment, else the share of value cues found
    in the source. ``negated`` is true when a negation marker precedes the
    value (in ``strict`` mode only within the value's own clause).
    """
    if mode not in {"strict", "preregistered"}:
        raise ValueError("mode must be strict or preregistered")
    v, s = _norm(value), _norm(source)
    if not v or not s:
        return {"paired": False, "coverage": 0.0, "unsupported": [], "negated": False}
    if v in s:
        coverage, unsupported, position = 1.0, [], s.find(v)
    else:
        cues = terms(v)
        found = {c for c in cues if c in s}
        coverage = len(found) / len(cues) if cues else 0.0
        unsupported = sorted(cues - found)
        position = min((s.find(c) for c in found), default=-1)
    prefix = s[:position] if position >= 0 else ""
    if mode == "strict":
        prefix = _CLAUSE_BREAK.split(prefix)[-1]
    negated = any(marker in prefix for marker in NEGATIONS)
    supported = coverage == 1.0 if mode == "strict" else coverage >= PAIR_THRESHOLD
    return {
        "paired": supported and not negated,
        "coverage": round(coverage, 4),
        "unsupported": unsupported[:8],
        "negated": negated,
        "mode": mode,
    }


def contained(value, source):
    """The trivial baseline: exact containment after normalization."""
    v, s = _norm(value), _norm(source)
    return bool(v) and v in s
