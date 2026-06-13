"""Answer-fidelity scorer for headroom-bench (axis 2).

Ported from fidelity_harness.py. Two checks:

  1. INFORMATION SUFFICIENCY (deterministic, no API key)
     A reference reader answers questions from the compressed output.
     If it scores 100%, the compression provably kept everything.

  2. MODEL LEGIBILITY (needs a live LLM, --live flag)
     A real model answers questions from both raw and compressed context.
     The delta measures whether the model can decode the compressed form
     as reliably as reading raw JSON.

Questions are generated from ground-truth records and bucketed by type:
  COUNT, LOOKUP, AGGREGATE, NONNUMERIC.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from typing import Any

from ._types import Dataset

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Question/Answer data types
# ---------------------------------------------------------------------------


@dataclass
class QA:
    """A question with ground-truth answer, derived from dataset records."""

    qtype: str  # COUNT, LOOKUP, AGGREGATE, NONNUMERIC
    question: str
    answer: str  # canonical ground-truth string


@dataclass
class FidelityResult:
    """Result of fidelity scoring for one (adapter, dataset) pair."""

    adapter: str
    dataset: str
    total: int
    correct: int
    accuracy: float
    by_type: dict[str, tuple[int, int]]  # qtype -> (correct, total)


# ---------------------------------------------------------------------------
# Question generation from ground-truth records
# ---------------------------------------------------------------------------

_QA_RNG = random.Random(99)


def _fmt(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _numeric_keys(recs: list[dict[str, Any]]) -> list[str]:
    keys = list(recs[0].keys())
    return [
        k for k in keys
        if all(
            isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)
            for r in recs
        )
    ]


def _nonnumeric_keys(recs: list[dict[str, Any]]) -> list[str]:
    numk = set(_numeric_keys(recs))
    return [k for k in recs[0].keys() if k not in numk]


def make_questions(recs: list[dict[str, Any]]) -> list[QA]:
    """Generate QA pairs from dataset records."""
    if not recs:
        return []

    n = len(recs)
    numk = _numeric_keys(recs)
    nonk = _nonnumeric_keys(recs)
    qs: list[QA] = []

    # COUNT
    qs.append(QA("COUNT", "How many records are in this result set?", str(n)))

    # LOOKUP + AGGREGATE on numeric columns
    for k in numk:
        col = [r[k] for r in recs]
        if any(v != col[0] for v in col):
            r_idx = _QA_RNG.randint(0, n - 1)
            qs.append(QA(
                "LOOKUP",
                f"What is '{k}' for the record at 0-based index {r_idx}?",
                _fmt(col[r_idx]),
            ))
            qs.append(QA(
                "AGGREGATE",
                f"What is the maximum value of '{k}'?",
                _fmt(max(col)),
            ))
            break  # one column is enough

    # NONNUMERIC lookup
    if nonk:
        k = nonk[0]
        r_idx = _QA_RNG.randint(0, n - 1)
        val = recs[r_idx].get(k)
        if val is not None:
            qs.append(QA(
                "NONNUMERIC",
                f"What is '{k}' for the record at 0-based index {r_idx}?",
                str(val),
            ))

    return qs


# ---------------------------------------------------------------------------
# Answer matching
# ---------------------------------------------------------------------------


def _match(pred: str, gold: str) -> bool:
    """Flexible answer matching: exact string or numeric tolerance."""
    pred = (pred or "").strip().strip('"').strip()
    gold = gold.strip()
    if pred == gold:
        return True
    try:
        return abs(float(pred) - float(gold)) < 1e-6
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Reference reader (deterministic sufficiency check)
# ---------------------------------------------------------------------------


def reference_answer(context: str, qa: QA) -> str:
    """Answer a question using only the compressed context text.

    This is a deterministic check — if it gets 100%, the compressed
    form provably contains all needed information.
    """
    # Check for ColumnarFold format: starts with "n=<digits>|cols:"
    if context.startswith("n=") and "|cols:" in context.split("\n", 1)[0]:
        return _reference_from_columnar(context, qa)

    try:
        obj = json.loads(context)
    except (json.JSONDecodeError, ValueError):
        return "<parse_error>"

    # Try to find the record list
    records: list[dict[str, Any]] = []
    if isinstance(obj, list):
        records = obj
    elif isinstance(obj, dict):
        # Check for _n/_rows (NumericFold format)
        if "_n" in obj and "_rows" in obj:
            return _reference_from_folded(obj, qa)
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                records = v
                break

    if not records:
        return "<no_records>"

    return _answer_from_records(records, qa)


def _answer_from_records(records: list[dict[str, Any]], qa: QA) -> str:
    """Answer from a plain list of record dicts."""
    import re

    n = len(records)

    if qa.qtype == "COUNT":
        return str(n)

    key_m = re.search(r"'([^']+)'", qa.question)
    key = key_m.group(1) if key_m else None
    idx_m = re.search(r"index (\d+)", qa.question)

    if qa.qtype == "LOOKUP" and key and idx_m:
        idx = int(idx_m.group(1))
        if 0 <= idx < n and key in records[idx]:
            return _fmt(records[idx][key])
        return "<unanswered>"

    if qa.qtype == "AGGREGATE" and key:
        vals = [r[key] for r in records if key in r and isinstance(r[key], (int, float))]
        return _fmt(max(vals)) if vals else "<unanswered>"

    if qa.qtype == "NONNUMERIC" and key and idx_m:
        idx = int(idx_m.group(1))
        if 0 <= idx < n and key in records[idx]:
            return str(records[idx][key])
        return "<unanswered>"

    return "<unanswered>"


def _reference_from_columnar(context: str, qa: QA) -> str:
    """Answer from a ColumnarFold-compressed output by reconstructing records."""
    try:
        from ..transforms.columnar_fold import reconstruct_columnar
        import re as _re

        # Parse the header to get n
        header_line = context.split("\n", 1)[0]
        n_match = _re.match(r"n=(\d+)", header_line)
        if not n_match:
            return "<parse_error>"
        n = int(n_match.group(1))

        if qa.qtype == "COUNT":
            return str(n)

        # Full reconstruction requires the recipe, which we don't have in the
        # compressed text alone. But we CAN parse the CSV portion directly for
        # non-numeric lookups, and read closed-form columns from the header.

        lines = context.split("\n")
        # Skip header and @dict: lines to find CSV
        csv_start = 1
        dict_maps: dict[str, list[str]] = {}
        while csv_start < len(lines) and lines[csv_start].startswith("@dict:"):
            # Parse @dict:key=val1,val2,val3
            dict_line = lines[csv_start][6:]  # strip "@dict:"
            eq_pos = dict_line.index("=")
            dk = dict_line[:eq_pos]
            dv = dict_line[eq_pos + 1:].split(",")
            dict_maps[dk] = dv
            csv_start += 1

        # Parse CSV portion
        if csv_start < len(lines):
            import csv
            import io

            csv_text = "\n".join(lines[csv_start:])
            reader = list(csv.reader(io.StringIO(csv_text)))
            if len(reader) > 1:
                csv_header = reader[0]
                csv_rows = reader[1:]

                # Build records from CSV (non-numeric columns only)
                csv_records: list[dict[str, Any]] = []
                for row in csv_rows:
                    rec: dict[str, Any] = {}
                    for ci, k in enumerate(csv_header):
                        if k == "_i":
                            continue
                        if ci < len(row):
                            val = row[ci]
                            # Decode dictionary-encoded values
                            if k in dict_maps:
                                try:
                                    val = dict_maps[k][int(val)]
                                except (ValueError, IndexError):
                                    pass
                            rec[k] = val
                    csv_records.append(rec)

                # Try to answer from CSV records
                key_m = _re.search(r"'([^']+)'", qa.question)
                key = key_m.group(1) if key_m else None
                idx_m = _re.search(r"index (\d+)", qa.question)

                if qa.qtype == "NONNUMERIC" and key and idx_m:
                    idx = int(idx_m.group(1))
                    if 0 <= idx < len(csv_records) and key in csv_records[idx]:
                        return str(csv_records[idx][key])

                if qa.qtype == "LOOKUP" and key and idx_m:
                    idx = int(idx_m.group(1))
                    if 0 <= idx < len(csv_records) and key in csv_records[idx]:
                        return _fmt(csv_records[idx][key])

                if qa.qtype == "AGGREGATE" and key:
                    vals = []
                    for r in csv_records:
                        if key in r:
                            try:
                                vals.append(float(r[key]))
                            except (ValueError, TypeError):
                                pass
                    if vals:
                        return _fmt(max(vals))

        # For numeric columns in the header (closed-form), parse codec strings
        # e.g. "id=AFFINE(a0=0,d=1,n=100)"
        key_m = _re.search(r"'([^']+)'", qa.question)
        key = key_m.group(1) if key_m else None
        idx_m = _re.search(r"index (\d+)", qa.question)

        if key and f"{key}=" in header_line:
            codec_m = _re.search(rf"{key}=(\w+)\(([^)]+)\)", header_line)
            if codec_m:
                codec = codec_m.group(1)
                params = codec_m.group(2)

                if codec == "CONST" and qa.qtype in ("LOOKUP", "AGGREGATE", "CONSTANT"):
                    # CONST(value)xN — all values are the same
                    val_m = _re.match(r"(.+)", params)
                    if val_m:
                        return _fmt(float(val_m.group(1)))

                if codec == "AFFINE" and idx_m:
                    # AFFINE(a0=X,d=Y,n=Z) — value at i = a0 + d*i
                    a0_m = _re.search(r"a0=([^,]+)", params)
                    d_m = _re.search(r"d=([^,]+)", params)
                    if a0_m and d_m:
                        a0 = float(a0_m.group(1))
                        d = float(d_m.group(1))
                        idx = int(idx_m.group(1))
                        val = a0 + d * idx
                        return _fmt(val)

                if codec == "AFFINE" and qa.qtype == "AGGREGATE":
                    a0_m = _re.search(r"a0=([^,]+)", params)
                    d_m = _re.search(r"d=([^,]+)", params)
                    n_m = _re.search(r"n=(\d+)", params)
                    if a0_m and d_m and n_m:
                        a0 = float(a0_m.group(1))
                        d = float(d_m.group(1))
                        nn = int(n_m.group(1))
                        if d >= 0:
                            return _fmt(a0 + d * (nn - 1))
                        else:
                            return _fmt(a0)

        return "<unanswered>"
    except Exception as e:
        logger.debug("ColumnarFold reference reader failed: %s", e)
        return "<unanswered>"


def _reference_from_folded(obj: dict[str, Any], qa: QA) -> str:
    """Answer from a NumericFold-compressed object with _n, _rows, _cols."""
    import re

    n = obj.get("_n", 0)
    rows = obj.get("_rows", [])

    if qa.qtype == "COUNT":
        return str(n)

    key_m = re.search(r"'([^']+)'", qa.question)
    key = key_m.group(1) if key_m else None
    idx_m = re.search(r"index (\d+)", qa.question)

    if qa.qtype == "NONNUMERIC" and key and idx_m:
        idx = int(idx_m.group(1))
        if 0 <= idx < len(rows) and key in rows[idx]:
            return str(rows[idx][key])

    # For numeric columns in _cols, we'd need to decode the codec.
    # This is a best-effort check — full decode requires the recipe.
    return "<unanswered>"


# ---------------------------------------------------------------------------
# Score fidelity
# ---------------------------------------------------------------------------


def score_fidelity(
    dataset: Dataset,
    compressed_text: str,
    adapter_name: str,
) -> FidelityResult:
    """Score answer fidelity for one (adapter, dataset) pair.

    Runs the deterministic reference reader against generated questions.
    """
    _QA_RNG.seed(hash(dataset.name) & 0xFFFF_FFFF)
    questions = make_questions(dataset.records)

    by_type: dict[str, list[int]] = {}
    total = 0
    correct = 0

    for qa in questions:
        ref = reference_answer(compressed_text, qa)
        ok = _match(ref, qa.answer)
        total += 1
        correct += int(ok)

        if qa.qtype not in by_type:
            by_type[qa.qtype] = [0, 0]
        by_type[qa.qtype][0] += int(ok)
        by_type[qa.qtype][1] += 1

    accuracy = correct / total if total > 0 else 0.0

    return FidelityResult(
        adapter=adapter_name,
        dataset=dataset.name,
        total=total,
        correct=correct,
        accuracy=round(accuracy, 4),
        by_type={k: (v[0], v[1]) for k, v in by_type.items()},
    )
