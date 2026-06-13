"""NumericFold — lossless numeric-column compression for JSON tool outputs.

Drop-in Headroom transform. Place at ``headroom/transforms/numeric_fold.py``.

SmartCrusher selects *which rows* survive a JSON tool output; it does not shrink
the numeric payload of the rows it keeps. Numbers tokenize terribly (GPT/Claude
split digit runs into <=3-digit groups), so a column of timestamps/ids/counters is
mostly redundant tokens. NumericFold re-encodes each numeric column with the
cheapest *reversible* codec, chosen by Minimum Description Length:

    CONST    all equal                       -> (value, n)
    AFFINE   constant 1st finite difference    -> (a0, d, n)        [arithmetic prog.]
    POLY_k   constant k-th finite difference   -> (k+1 coeffs, n)   [Newton differences]
    DELTA    base + zig-zag integer deltas
    RATIONAL continued-fraction convergent p/q                      [Ramanujan-style]
    RAW      fallback; left INLINE (see below)

Runs as a post-SmartCrusher transform: ContentRouter/SmartCrusher select rows,
NumericFold folds the numeric columns of the survivors. The fold ``recipe`` is
stored in the CCR store so the original is recoverable via headroom_retrieve.

GATING (validated empirically, folded-vs-raw ΔAcc on gemini flash/pro, GH #4/#5):
  * AFFINE/CONST: neutral-to-helpful on all tiers -> ON by default.
  * POLY_k: small models can't decode it (flash -88%, pro +0%) -> OFF by default,
    enable via ``NumericFoldConfig.enable_poly`` for high-capability tiers.
  * RAW: hoisting a flat array hurts weak-model positional lookups (flash -25%),
    so RAW columns are kept INLINE by default (``hoist_raw=False``). The proper
    token-recovery path is columnar transposition with an index (GH #22).

Pure stdlib + Fraction (exact, no float drift). Token counting uses Headroom's
tokenizer at the transform boundary, so the in-product numbers are real tiktoken.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ..config import CCRConfig, TransformResult
from ..tokenizer import Tokenizer
from ..utils import compute_short_hash, create_tool_digest_marker, deep_copy_messages
from .base import Transform

logger = logging.getLogger(__name__)


# ─── Config ───────────────────────────────────────────────────────────────


@dataclass
class NumericFoldConfig:
    """Configuration for NumericFold. Mirrors the SmartCrusherConfig style."""

    enabled: bool = True
    min_tokens_to_fold: int = 80      # skip tiny tool outputs
    min_rows: int = 8                 # need enough rows for a codec to pay off
    rel_tol: float = 1e-9             # RATIONAL within-tolerance bound
    enable_rational: bool = True
    enable_poly: bool = False         # GATED — only legible on strong tiers (#5)
    max_poly_order: int = 3
    enable_recurrence: bool = True    # linear recurrence codec (Fibonacci-like sequences)
    max_recurrence_order: int = 4     # max order of linear recurrence to detect
    hoist_raw: bool = False           # keep RAW columns inline (#4); True dedups keys


# ─── Codec core (config-aware) ────────────────────────────────────────────


@dataclass
class ColumnFold:
    codec: str
    recipe: dict
    payload_str: str
    n: int
    lossless: bool = True
    tol: str | None = None


def _to_fraction(x: Any) -> Fraction | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        return Fraction(repr(x))
    if isinstance(x, str):
        try:
            return Fraction(x)
        except (ValueError, ZeroDivisionError):
            return None
    return None


def _is_intlike(values: list[Fraction]) -> bool:
    return all(v.denominator == 1 for v in values)


def _finite_diff_table(seq: list[Fraction]) -> list[list[Fraction]]:
    rows = [seq]
    cur = seq
    while len(cur) > 1:
        nxt = [cur[i + 1] - cur[i] for i in range(len(cur) - 1)]
        rows.append(nxt)
        if all(d == nxt[0] for d in nxt):
            break
        cur = nxt
    return rows


def _cf_convergent(x: Fraction, tol: Fraction, max_den: int = 10_000) -> Fraction | None:
    if x == 0:
        return Fraction(0)
    a = x
    h0, h1, k0, k1 = 0, 1, 1, 0
    for _ in range(64):
        ai = math.floor(a)
        h2, k2 = ai * h1 + h0, ai * k1 + k0
        if k2 == 0 or k2 > max_den:
            break
        conv = Fraction(h2, k2)
        if abs(conv - x) <= tol:
            return conv
        h0, h1, k0, k1 = h1, h2, k1, k2
        frac = a - ai
        if frac == 0:
            return Fraction(h2, k2)
        a = 1 / frac
    return None


def _num_str(fr: Fraction) -> str:
    if fr.denominator == 1:
        return str(fr.numerator)
    dec = repr(fr.numerator / fr.denominator)
    pq = f"{fr.numerator}/{fr.denominator}"
    return dec if len(dec) <= len(pq) else pq


def _est(text: str) -> int:
    """Cheap MDL ranking metric (codec selection only, not reporting)."""
    n = 0
    for tok in re.findall(r"\d+|[A-Za-z]+|\s+|[^\sA-Za-z\d]", text):
        n += math.ceil(len(tok) / 3) if tok.isdigit() else 1
    return n


def _detect_linear_recurrence(
    values: list[Fraction], max_order: int,
) -> tuple[list[Fraction], list[Fraction]] | None:
    """Detect if a sequence satisfies a linear recurrence of order <= max_order.

    Returns (coeffs, initial_values) if found, None otherwise.
    coeffs[i] means T_r = coeffs[0]*T_{r-1} + coeffs[1]*T_{r-2} + ...

    Uses the Berlekamp-Massey approach: try each order d from 1 to max_order,
    set up the system T_r = c0*T_{r-1} + ... + c_{d-1}*T_{r-d} and check if
    it holds exactly for all values.
    """
    n = len(values)

    for d in range(1, min(max_order + 1, n // 2)):
        # Need at least 2d values: d for initial conditions, d for the system
        if n < 2 * d:
            continue

        # Solve for coefficients using the first 2d values
        # Build matrix: for rows d..2d-1, each row is [T_{r-1}, T_{r-2}, ..., T_{r-d}]
        # and target is T_r
        from fractions import Fraction as F

        # Set up linear system via Gaussian elimination
        rows_needed = d
        matrix = []
        targets = []
        for r in range(d, d + rows_needed):
            row = [values[r - 1 - j] for j in range(d)]
            matrix.append(row)
            targets.append(values[r])

        # Gaussian elimination with exact fractions
        aug = [row + [t] for row, t in zip(matrix, targets)]
        for col in range(d):
            # Find pivot
            pivot = None
            for row in range(col, d):
                if aug[row][col] != 0:
                    pivot = row
                    break
            if pivot is None:
                break
            aug[col], aug[pivot] = aug[pivot], aug[col]
            for row in range(d):
                if row != col and aug[row][col] != 0:
                    factor = aug[row][col] / aug[col][col]
                    for j in range(d + 1):
                        aug[row][j] -= factor * aug[col][j]
        else:
            # Extract coefficients
            coeffs = [aug[i][d] / aug[i][i] for i in range(d)]

            # Verify against ALL remaining values
            ok = True
            for r in range(d, n):
                predicted = sum(coeffs[j] * values[r - 1 - j] for j in range(d))
                if predicted != values[r]:
                    ok = False
                    break

            if ok:
                return coeffs, list(values[:d])

    return None


def _reconstruct_recurrence(
    coeffs: list[str], init: list[str], n: int,
) -> list[int | float]:
    """Reconstruct a sequence from linear recurrence coefficients."""
    c = [Fraction(x) for x in coeffs]
    vals = [Fraction(x) for x in init]
    d = len(c)

    for _ in range(n - d):
        nxt = sum(c[j] * vals[-(j + 1)] for j in range(d))
        vals.append(nxt)

    return [int(v) if v.denominator == 1 else float(v) for v in vals[:n]]


def fold_column(values: list[Any], cfg: NumericFoldConfig) -> ColumnFold:
    """Pick the minimum-cost reversible encoding for one numeric column."""
    fr = [_to_fraction(v) for v in values]
    if any(f is None for f in fr):
        raw = json.dumps(values, separators=(",", ":"))
        return ColumnFold("RAW", {"values": values}, raw, len(values))
    fr = [f for f in fr if f is not None]
    n = len(fr)
    cands: list[ColumnFold] = []

    raw_str = json.dumps([int(f) if f.denominator == 1 else float(f) for f in fr],
                         separators=(",", ":"))
    cands.append(ColumnFold("RAW", {"values": raw_str}, raw_str, n))

    if all(f == fr[0] for f in fr):
        cands.append(ColumnFold("CONST", {"value": _num_str(fr[0]), "n": n},
                                f"CONST({_num_str(fr[0])})x{n}", n))

    if n >= 3:
        rows = _finite_diff_table(fr)
        order = len(rows) - 1
        constant_bottom = len(rows[-1]) >= 1 and all(d == rows[-1][0] for d in rows[-1])
        affine = order == 1
        allow = affine or (cfg.enable_poly and order <= cfg.max_poly_order)
        if constant_bottom and allow:
            leading = [row[0] for row in rows]
            coeffs = [str(c) for c in leading]
            if affine:
                p = f"AFFINE(a0={_num_str(leading[0])},d={_num_str(leading[1])},n={n})"
                cands.append(ColumnFold("AFFINE", {"coeffs": coeffs, "n": n}, p, n))
            else:
                body = ",".join(_num_str(c) for c in leading)
                cands.append(ColumnFold(f"POLY{order}", {"coeffs": coeffs, "n": n},
                                        f"POLY{order}(d0={body},n={n})", n))

    if n >= 3 and _is_intlike(fr):
        ints = [f.numerator for f in fr]
        deltas = [ints[0]] + [ints[i] - ints[i - 1] for i in range(1, n)]
        body = ",".join(str(d) for d in deltas)
        cands.append(ColumnFold("DELTA", {"deltas": deltas}, f"DELTA(base={ints[0]};{body})", n))

    # Linear recurrence codec (catches Fibonacci-like, exponential, trace sequences)
    if cfg.enable_recurrence and n >= 4 and _is_intlike(fr):
        rec = _detect_linear_recurrence(fr, cfg.max_recurrence_order)
        if rec is not None:
            coeffs_fr, init_fr = rec
            d = len(coeffs_fr)
            coeffs_s = [str(c) for c in coeffs_fr]
            init_s = [str(v) for v in init_fr]
            body_c = ",".join(_num_str(c) for c in coeffs_fr)
            body_i = ",".join(_num_str(v) for v in init_fr)
            payload = f"RECURRENCE(coeffs=[{body_c}],init=[{body_i}],n={n})"
            cands.append(ColumnFold(
                f"RECURRENCE{d}",
                {"coeffs": coeffs_s, "init": init_s, "n": n},
                payload, n,
            ))

    if cfg.enable_rational and not _is_intlike(fr):
        tolF = Fraction(cfg.rel_tol).limit_denominator(10**12)
        approx, ok, exact = [], True, True
        for f in fr:
            conv = _cf_convergent(f, max(tolF, abs(f) * tolF))
            if conv is None:
                ok = False
                break
            exact = exact and (conv == f)
            approx.append(conv)
        if ok:
            body = ",".join(_num_str(c) for c in approx)
            cands.append(ColumnFold("RATIONAL", {"rationals": [str(c) for c in approx], "n": n},
                                    f"RATIONAL[{body}]", n, lossless=exact,
                                    tol=None if exact else str(cfg.rel_tol)))

    return min(cands, key=lambda c: _est(c.payload_str))


def reconstruct_column(fold: ColumnFold) -> list:
    c, r = fold.codec, fold.recipe
    if c == "RAW":
        v = r["values"]
        return json.loads(v) if isinstance(v, str) else v
    if c == "CONST":
        val = Fraction(str(r["value"]))
        return [(float(val) if val.denominator != 1 else int(val))] * r["n"]
    if c == "AFFINE" or c.startswith("POLY"):
        leading = [Fraction(x) for x in r["coeffs"]]
        n, order = r["n"], len(r["coeffs"]) - 1
        rows = [[leading[-1]] * (n - order)]
        for lvl in range(order - 1, -1, -1):
            cur = [leading[lvl]]
            for d in rows[0]:
                cur.append(cur[-1] + d)
            rows.insert(0, cur)
        return [int(x) if x.denominator == 1 else float(x) for x in rows[0][:n]]
    if c == "DELTA":
        out = [r["deltas"][0]]
        for d in r["deltas"][1:]:
            out.append(out[-1] + d)
        return out
    if c == "RATIONAL":
        return [float(Fraction(x)) for x in r["rationals"]]
    if c.startswith("RECURRENCE"):
        return _reconstruct_recurrence(r["coeffs"], r["init"], r["n"])
    raise ValueError(f"unknown codec {c}")


def _extract_records(obj: Any) -> tuple[list[dict] | None, str | None]:
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        return obj, None
    if isinstance(obj, dict):
        for k in ("results", "data", "items", "rows", "records", "matches", "issues", "files", "entries", "series"):
            v = obj.get(k)
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                return v, k
    return None, None


def fold_tool_output(raw_json: str, cfg: NumericFoldConfig) -> tuple[str, dict] | None:
    """Fold numeric columns of a JSON tool output. Returns (folded_text, recipe)
    or None if there's nothing foldable. Non-numeric content is left intact."""
    try:
        obj = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        return None
    records, _ = _extract_records(obj)
    if not records or len(records) < cfg.min_rows:
        return None

    keys = list(records[0].keys())
    numeric_keys = [k for k in keys
                    if all(isinstance(rec.get(k), (int, float)) and not isinstance(rec.get(k), bool)
                           for rec in records)]
    if not numeric_keys:
        return None

    folds = {k: fold_column([rec[k] for rec in records], cfg) for k in numeric_keys}
    # Only hoist columns that actually compress. RAW stays inline unless hoist_raw.
    folded_keys = [k for k in numeric_keys
                   if folds[k].codec != "RAW" or cfg.hoist_raw]
    if not folded_keys:
        return None
    inline_keys = [k for k in keys if k not in folded_keys]
    inline_rows = [{k: rec.get(k) for k in inline_keys} for rec in records] if inline_keys else []

    folded_obj = {
        "_schema": keys,
        "_n": len(records),
        "_cols": {k: folds[k].payload_str for k in folded_keys},
        "_rows": inline_rows,
    }
    recipe = {
        "codec": "NUMERICFOLD",
        "n": len(records),
        "columns": {k: {"codec": folds[k].codec, "recipe": folds[k].recipe,
                        "lossless": folds[k].lossless, "tol": folds[k].tol}
                    for k in folded_keys},
    }
    return json.dumps(folded_obj, separators=(",", ":")), recipe


# ─── Transform ────────────────────────────────────────────────────────────


class NumericFold(Transform):
    """Post-SmartCrusher numeric-column folding transform."""

    name = "numeric_fold"

    def __init__(self, config: NumericFoldConfig | None = None,
                 ccr_config: CCRConfig | None = None):
        self.config = config or NumericFoldConfig()
        self._ccr_config = ccr_config or CCRConfig()

    def should_apply(self, messages, tokenizer, **kwargs) -> bool:
        return self.config.enabled

    def _store_recipe(self, recipe: dict, folded_text: str) -> str | None:
        """Best-effort CCR write so headroom_retrieve can rebuild the original.
        Returns a 12-char hash marker or None. Mirrors SmartCrusher's pattern."""
        if not self._ccr_config.enabled:
            return None
        try:
            from ..cache.compression_store import get_compression_store
            h = compute_short_hash(folded_text)
            get_compression_store().store(
                original=json.dumps(recipe, separators=(",", ":")),
                compressed=folded_text,
                tool_name=None,
                query_context=None,
                compression_strategy="numeric_fold",
                explicit_hash=h,
            )
            return h
        except Exception as e:  # pragma: no cover - best effort
            logger.debug("NumericFold CCR store failed (non-fatal): %s", e)
            return None

    def _fold_content(self, content: str, tokenizer: Tokenizer) -> tuple[str, str] | None:
        if tokenizer.count_text(content) < self.config.min_tokens_to_fold:
            return None
        out = fold_tool_output(content, self.config)
        if out is None:
            return None
        folded_text, recipe = out
        # Only keep the fold if it actually reduces tokens.
        if tokenizer.count_text(folded_text) >= tokenizer.count_text(content):
            return None
        codecs = ",".join(sorted({c["codec"] for c in recipe["columns"].values()}))
        self._store_recipe(recipe, folded_text)
        return folded_text, codecs

    def apply(self, messages: list[dict[str, Any]], tokenizer: Tokenizer,
              **kwargs: Any) -> TransformResult:
        tokens_before = tokenizer.count_messages(messages)
        result_messages = deep_copy_messages(messages)
        transforms_applied: list[str] = []
        markers_inserted: list[str] = []
        frozen = kwargs.get("frozen_message_count", 0)
        folded_count = 0

        for idx, msg in enumerate(result_messages):
            if idx < frozen:
                continue
            # OpenAI-style tool messages.
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                res = self._fold_content(msg["content"], tokenizer)
                if res:
                    folded_text, codecs = res
                    marker = create_tool_digest_marker(compute_short_hash(msg["content"]))
                    msg["content"] = folded_text + "\n" + marker
                    markers_inserted.append(marker)
                    transforms_applied.append(f"numeric_fold:{codecs}")
                    folded_count += 1
            # Anthropic-style tool_result blocks.
            content = msg.get("content")
            if isinstance(content, list):
                for i, block in enumerate(content):
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    tc = block.get("content")
                    if not isinstance(tc, str):
                        continue
                    res = self._fold_content(tc, tokenizer)
                    if res:
                        folded_text, codecs = res
                        marker = create_tool_digest_marker(compute_short_hash(tc))
                        content[i]["content"] = folded_text + "\n" + marker
                        markers_inserted.append(marker)
                        transforms_applied.append(f"numeric_fold:{codecs}")
                        folded_count += 1

        if folded_count:
            transforms_applied.insert(0, f"numeric_fold:{folded_count}")

        return TransformResult(
            messages=result_messages,
            tokens_before=tokens_before,
            tokens_after=tokenizer.count_messages(result_messages),
            transforms_applied=transforms_applied,
            markers_inserted=markers_inserted,
            warnings=[],
        )
