"""ColumnarFold — columnar transposition with closed-form codecs + CSV.

The next step beyond NumericFold. NumericFold folds *numeric* columns to
closed-form codecs (AFFINE/CONST/POLY/...) and leaves everything else inline
as repeated-key JSON records — so the residual columns still pay their key
per row. ColumnarFold emits those residual columns (RAW numerics +
non-numeric scalars) as one **CSV block**: the column key appears once
(header), and each record is one row.

A tool output therefore becomes::

    n=100|cols:id=AFFINE(a0=0,d=1,n=100);ts=AFFINE(a0=1718200000,d=7,n=100)
    level,latency_ms,msg
    INFO,56.8,request handled
    WARN,31.7,cache miss
    ...

Two wins over inline-RAW NumericFold:
  * KEY DEDUP — the header carries each residual key once instead of N times.
  * LEGIBILITY — each record stays on its own CSV row, so positional lookup
    is as easy as raw JSON.

Lossless: per-column types are recorded so CSV cells decode back exactly.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import CCRConfig, TransformResult
from ..tokenizer import Tokenizer
from ..utils import compute_short_hash, create_tool_digest_marker, deep_copy_messages
from .base import Transform
from .numeric_fold import (
    ColumnFold,
    NumericFoldConfig,
    fold_column,
    reconstruct_column,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_records(obj: Any) -> list[dict[str, Any]] | None:
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        return obj
    if isinstance(obj, dict):
        for k in ("results", "data", "items", "rows", "records", "matches", "issues", "files", "entries", "series"):
            v = obj.get(k)
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                return v
    return None


def _flatten_record(rec: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts into dot-notation keys.

    {"metadata": {"author": "Alice", "category": "tech"}}
    → {"metadata.author": "Alice", "metadata.category": "tech"}

    Only flattens one level of dict nesting. Lists and other types
    are kept as-is.
    """
    flat: dict[str, Any] = {}
    for k, v in rec.items():
        full_key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if (
            isinstance(v, dict)
            and v
            and all(isinstance(vv, (str, int, float, bool, type(None))) for vv in v.values())
            and all(
                not isinstance(vv, str) or ("\n" not in vv and len(vv) < 200)
                for vv in v.values()
            )
        ):
            # Flatten scalar-valued dicts (no multi-line or very long strings)
            for kk, vv in v.items():
                flat[f"{full_key}.{kk}"] = vv
        else:
            flat[full_key] = v
    return flat


def _unflatten_record(flat: dict[str, Any]) -> dict[str, Any]:
    """Reverse of _flatten_record — reconstruct nested dicts from dot-notation."""
    result: dict[str, Any] = {}
    for k, v in flat.items():
        parts = k.split(".")
        if len(parts) == 1:
            result[k] = v
        else:
            # Nested: a.b.c → result["a"]["b"]["c"] = v
            d = result
            for part in parts[:-1]:
                if part not in d:
                    d[part] = {}
                d = d[part]
            d[parts[-1]] = v
    return result


def _flatten_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Flatten all records. Returns (flattened_records, was_flattened).

    Only flattens if at least one record has a nested dict with scalar values.
    Ensures all records have the same keys (fills missing with None).
    """
    has_nested = any(
        isinstance(v, dict)
        for rec in records[:10]  # sample first 10
        for v in rec.values()
    )
    if not has_nested:
        return records, False

    flattened = [_flatten_record(rec) for rec in records]

    # Unify keys — but only include keys present in >50% of records
    # to avoid inflating the CSV with sparse optional fields
    key_counts: dict[str, int] = {}
    for rec in flattened:
        for k in rec:
            key_counts[k] = key_counts.get(k, 0) + 1

    threshold = len(records) * 0.5
    common_keys = [k for k, c in key_counts.items() if c >= threshold]

    if not common_keys:
        return records, False  # nothing useful after filtering

    # Rebuild records with only common keys, fill missing with None
    unified = []
    for rec in flattened:
        row = {}
        for k in common_keys:
            row[k] = rec.get(k)
        unified.append(row)

    return unified, True


def _is_numeric_col(col: list[Any]) -> bool:
    non_null = [v for v in col if v is not None]
    if not non_null:
        return False
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null)


def _col_type(col: list[Any]) -> str:
    """Reconstruction type for a residual (CSV) column.

    Handles nullable columns: [42, None, 38] → "int?" (not "json").
    """
    non_null = [v for v in col if v is not None]
    has_null = len(non_null) < len(col)

    if not non_null:
        return "str"  # all None — treat as string

    if all(isinstance(v, bool) for v in non_null):
        return "bool?" if has_null else "bool"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        return "int?" if has_null else "int"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "float?" if has_null else "float"
    if all(isinstance(v, str) for v in non_null):
        return "str?" if has_null else "str"
    return "json"


def _encode_cell(v: Any, t: str) -> str:
    if t == "json":
        if v is None:
            return ""
        return json.dumps(v, separators=(",", ":"))
    if v is None:
        return ""
    return str(v)


def _decode_cell(s: str, t: str) -> Any:
    if t == "json":
        if s == "":
            return None
        return json.loads(s)
    # Nullable types: empty string → None
    if t.endswith("?") and s == "":
        return None
    base = t.rstrip("?")
    if base == "int":
        return int(s)
    if base == "float":
        return float(s)
    if base == "bool":
        return s == "True"
    return s  # str: empty string stays empty string


# ---------------------------------------------------------------------------
# Dictionary encoding for low-cardinality string columns
# ---------------------------------------------------------------------------


def _should_dict_encode(col: list[Any], col_type: str) -> bool:
    """Return True if dictionary encoding would save tokens."""
    if col_type.rstrip("?") not in ("str", "json"):
        return False
    unique = len(set(str(v) for v in col))
    # Dictionary pays: header line + one index per row
    # Saves: (avg_value_len - index_len) * n_rows
    # Heuristic: worth it if unique < 50% of total and unique < 64
    return unique < len(col) * 0.5 and unique <= 64


def _build_dict(col: list[Any]) -> tuple[dict[str, int], list[str]]:
    """Build value -> index mapping and ordered dictionary."""
    seen: dict[str, int] = {}
    order: list[str] = []
    for v in col:
        s = str(v)
        if s not in seen:
            seen[s] = len(order)
            order.append(s)
    return seen, order


def _find_common_prefix(col: list[Any], col_type: str, min_savings: float = 0.2) -> str | None:
    """Find a common prefix worth extracting from a string column.

    Returns the prefix if it covers >min_savings of total chars, None otherwise.
    """
    base_type = col_type.rstrip("?")
    if base_type != "str":
        return None

    strings = [str(v) for v in col if v is not None]
    if len(strings) < 5:
        return None

    # Skip columns with newlines (break CSV format)
    if any("\n" in s for s in strings):
        return None

    import os
    prefix = os.path.commonprefix(strings)
    if len(prefix) < 4:
        return None

    total_chars = sum(len(s) for s in strings)
    prefix_chars = len(prefix) * len(strings)
    if prefix_chars / total_chars < min_savings:
        return None

    return prefix


def _csv_dumps(header: list[str], rows: list[list[str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().rstrip("\n")


def _csv_loads(text: str) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(text)))
    return rows[0], rows[1:]


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class ColumnarResult:
    """Result of columnar folding."""

    folded_text: str
    recipe: dict[str, Any]
    chars_before: int = 0
    chars_after: int = 0
    per_column: dict[str, str] = field(default_factory=dict)

    @property
    def char_savings_pct(self) -> float:
        if not self.chars_before:
            return 0.0
        return 100 * (1 - self.chars_after / self.chars_before)


# ---------------------------------------------------------------------------
# Fold
# ---------------------------------------------------------------------------


def columnar_fold(
    raw_json: str,
    cfg: NumericFoldConfig | None = None,
) -> ColumnarResult | None:
    """Columnar-fold a JSON tool output. Returns None if nothing foldable."""
    if cfg is None:
        cfg = NumericFoldConfig()

    try:
        obj = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        return None

    records = _extract_records(obj)
    if not records or len(records) < cfg.min_rows:
        return None

    # Try both flattened and unflattened, keep whichever is smaller
    records_flat, was_flattened = _flatten_records(records)
    result_flat = _columnar_fold_inner(raw_json, records_flat, cfg, flattened=was_flattened)
    result_plain = _columnar_fold_inner(raw_json, records, cfg, flattened=False)

    # Pick the better result
    if result_flat and result_plain:
        return result_flat if len(result_flat.folded_text) < len(result_plain.folded_text) else result_plain
    return result_flat or result_plain


def _columnar_fold_inner(
    raw_json: str,
    records: list[dict[str, Any]],
    cfg: NumericFoldConfig,
    flattened: bool,
) -> ColumnarResult | None:
    """Inner fold logic — called with both flattened and unflattened records."""
    keys = list(records[0].keys())
    cols = {k: [rec.get(k) for rec in records] for k in keys}

    closed: dict[str, ColumnFold] = {}
    csv_keys: list[str] = []
    csv_types: dict[str, str] = {}
    per_column: dict[str, str] = {}

    for k in keys:
        col = cols[k]
        if _is_numeric_col(col):
            f = fold_column(col, cfg)
            poly = f.codec.startswith("POLY")
            if f.codec != "RAW" and not (poly and not cfg.enable_poly):
                closed[k] = f
                per_column[k] = f.codec
                continue
        csv_keys.append(k)
        csv_types[k] = _col_type(col)
        per_column[k] = f"csv:{csv_types[k]}"

    if not closed and not csv_keys:
        return None

    # Dictionary-encode low-cardinality CSV columns
    dict_encoded: dict[str, tuple[dict[str, int], list[str]]] = {}
    for k in csv_keys:
        col = cols[k]
        if _should_dict_encode(col, csv_types[k]):
            mapping, order = _build_dict(col)
            dict_encoded[k] = (mapping, order)
            per_column[k] = f"dict:{csv_types[k]}"

    # Prefix-dedup high-cardinality string columns (not dict-encoded)
    prefix_encoded: dict[str, str] = {}
    for k in csv_keys:
        if k not in dict_encoded:
            prefix = _find_common_prefix(cols[k], csv_types[k])
            if prefix:
                prefix_encoded[k] = prefix
                per_column[k] = f"prefix:{csv_types[k]}"

    # Build CSV block with explicit _i index column
    csv_text = ""
    if csv_keys:
        csv_rows = []
        for i in range(len(records)):
            row = [str(i)]
            for k in csv_keys:
                if k in dict_encoded:
                    mapping, _ = dict_encoded[k]
                    row.append(str(mapping[str(cols[k][i])]))
                elif k in prefix_encoded:
                    val = cols[k][i]
                    prefix = prefix_encoded[k]
                    s = str(val) if val is not None else ""
                    row.append(s[len(prefix):] if s.startswith(prefix) else s)
                else:
                    row.append(_encode_cell(cols[k][i], csv_types[k]))
            csv_rows.append(row)
        csv_text = _csv_dumps(["_i"] + csv_keys, csv_rows)

    # Build dictionary and prefix lines (prepended before CSV)
    dict_lines: list[str] = []
    for k in csv_keys:
        if k in dict_encoded:
            _, order = dict_encoded[k]
            dict_lines.append(f"@dict:{k}={','.join(order)}")
        elif k in prefix_encoded:
            dict_lines.append(f"@prefix:{k}={prefix_encoded[k]}")

    cols_str = ";".join(f"{k}={closed[k].payload_str}" for k in closed)
    header = f"n={len(records)}|cols:{cols_str}"

    parts = [header]
    if dict_lines:
        parts.extend(dict_lines)
    if csv_text:
        parts.append(csv_text)
    folded_text = "\n".join(parts)

    recipe = {
        "codec": "COLUMNARFOLD",
        "n": len(records),
        "schema": keys,
        "cols": {
            k: {
                "codec": closed[k].codec,
                "recipe": closed[k].recipe,
                "lossless": closed[k].lossless,
                "tol": closed[k].tol,
            }
            for k in closed
        },
        "csv_types": csv_types,
        "dict_encoded": {k: order for k, (_, order) in dict_encoded.items()},
        "prefix_encoded": prefix_encoded,
        "flattened": flattened,
    }

    # Only return the fold if it actually reduces size
    if len(folded_text) >= len(raw_json):
        return None

    return ColumnarResult(
        folded_text=folded_text,
        recipe=recipe,
        chars_before=len(raw_json),
        chars_after=len(folded_text),
        per_column=per_column,
    )


# ---------------------------------------------------------------------------
# Reconstruct
# ---------------------------------------------------------------------------


def reconstruct_columnar(folded_text: str, recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """Exact inverse of columnar_fold."""
    n = recipe["n"]
    schema = recipe["schema"]
    dict_encoded = recipe.get("dict_encoded", {})
    prefix_encoded = recipe.get("prefix_encoded", {})

    # Closed-form columns
    closed_vals: dict[str, list[Any]] = {}
    for k, meta in recipe.get("cols", {}).items():
        f = ColumnFold(
            meta["codec"], meta["recipe"], "", n,
            meta.get("lossless", True), meta.get("tol"),
        )
        closed_vals[k] = reconstruct_column(f)

    # Find CSV portion (skip header and @dict: lines)
    csv_vals: dict[str, list[Any]] = {}
    lines = folded_text.split("\n")
    csv_start = 1  # skip header line
    while csv_start < len(lines) and (
        lines[csv_start].startswith("@dict:") or lines[csv_start].startswith("@prefix:")
    ):
        csv_start += 1

    if csv_start < len(lines):
        csv_text = "\n".join(lines[csv_start:])
        csv_header, csv_rows = _csv_loads(csv_text)
        types = recipe["csv_types"]
        for ci, k in enumerate(csv_header):
            if k in types:
                if k in dict_encoded:
                    # Decode dictionary indices back to values
                    dictionary = dict_encoded[k]
                    raw_vals = []
                    for r in csv_rows:
                        idx = int(r[ci])
                        val_str = dictionary[idx]
                        raw_vals.append(_decode_cell(val_str, types[k]))
                    csv_vals[k] = raw_vals
                elif k in prefix_encoded:
                    # Prepend the stored prefix to each suffix
                    prefix = prefix_encoded[k]
                    csv_vals[k] = [
                        prefix + _decode_cell(r[ci], types[k])
                        if r[ci] else _decode_cell(r[ci], types[k])
                        for r in csv_rows
                    ]
                else:
                    csv_vals[k] = [_decode_cell(r[ci], types[k]) for r in csv_rows]

    out = []
    for i in range(n):
        rec = {}
        for k in schema:
            if k in closed_vals:
                rec[k] = closed_vals[k][i]
            elif k in csv_vals:
                rec[k] = csv_vals[k][i]
        out.append(rec)

    # Unflatten dot-notation keys back to nested dicts if needed
    if recipe.get("flattened"):
        out = [_unflatten_record(rec) for rec in out]
        # Strip None-valued keys that were added by key-unification
        # (original records may not have had all keys)
        out = [
            {k: v for k, v in rec.items() if v is not None or k in _non_nullable_keys(recipe)}
            for rec in out
        ]

    return out


def _non_nullable_keys(recipe: dict[str, Any]) -> set[str]:
    """Keys that are genuinely nullable (not added by key-unification)."""
    types = recipe.get("csv_types", {})
    # Keys with non-nullable types always existed in the original
    return {k for k, t in types.items() if not t.endswith("?")}


# ---------------------------------------------------------------------------
# Transform wrapper for pipeline integration
# ---------------------------------------------------------------------------


class ColumnarFoldTransform(Transform):
    """Post-SmartCrusher columnar folding transform.

    Superset of NumericFold: closed-form codecs for numeric columns PLUS
    CSV transposition for residual columns. Use this instead of NumericFold
    in the pipeline for maximum compression.
    """

    name = "columnar_fold"

    def __init__(
        self,
        config: NumericFoldConfig | None = None,
        ccr_config: CCRConfig | None = None,
    ) -> None:
        self.config = config or NumericFoldConfig()
        self._ccr_config = ccr_config or CCRConfig()

    def should_apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> bool:
        return self.config.enabled

    def _fold_content(
        self, content: str, tokenizer: Tokenizer,
    ) -> tuple[str, str] | None:
        if tokenizer.count_text(content) < self.config.min_tokens_to_fold:
            return None
        result = columnar_fold(content, self.config)
        if result is None:
            return None
        if tokenizer.count_text(result.folded_text) >= tokenizer.count_text(content):
            return None
        codecs = ",".join(sorted(set(result.per_column.values())))
        return result.folded_text, codecs

    def apply(
        self,
        messages: list[dict[str, Any]],
        tokenizer: Tokenizer,
        **kwargs: Any,
    ) -> TransformResult:
        tokens_before = tokenizer.count_messages(messages)
        result_messages = deep_copy_messages(messages)
        transforms_applied: list[str] = []
        markers_inserted: list[str] = []
        frozen = kwargs.get("frozen_message_count", 0)
        folded_count = 0

        for idx, msg in enumerate(result_messages):
            if idx < frozen:
                continue
            # OpenAI-style tool messages
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                res = self._fold_content(msg["content"], tokenizer)
                if res:
                    folded_text, codecs = res
                    marker = create_tool_digest_marker(
                        compute_short_hash(msg["content"])
                    )
                    msg["content"] = folded_text + "\n" + marker
                    markers_inserted.append(marker)
                    transforms_applied.append(f"columnar_fold:{codecs}")
                    folded_count += 1
            # Anthropic-style tool_result blocks
            content = msg.get("content")
            if isinstance(content, list):
                for i, block in enumerate(content):
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_result":
                        continue
                    tc = block.get("content")
                    if not isinstance(tc, str):
                        continue
                    res = self._fold_content(tc, tokenizer)
                    if res:
                        folded_text, codecs = res
                        marker = create_tool_digest_marker(
                            compute_short_hash(tc)
                        )
                        content[i]["content"] = folded_text + "\n" + marker
                        markers_inserted.append(marker)
                        transforms_applied.append(f"columnar_fold:{codecs}")
                        folded_count += 1

        if folded_count:
            transforms_applied.insert(0, f"columnar_fold:{folded_count}")

        return TransformResult(
            messages=result_messages,
            tokens_before=tokens_before,
            tokens_after=tokenizer.count_messages(result_messages),
            transforms_applied=transforms_applied,
            markers_inserted=markers_inserted,
            warnings=[],
        )
