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


def _is_numeric_col(col: list[Any]) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in col)


def _col_type(col: list[Any]) -> str:
    """Reconstruction type for a residual (CSV) column."""
    if all(isinstance(v, bool) for v in col):
        return "bool"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in col):
        return "int"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in col):
        return "float"
    if all(isinstance(v, str) for v in col):
        return "str"
    return "json"


def _encode_cell(v: Any, t: str) -> str:
    if t == "json":
        return json.dumps(v, separators=(",", ":"))
    return "" if v is None else str(v)


def _decode_cell(s: str, t: str) -> Any:
    if t == "json":
        return json.loads(s)
    if t == "int":
        return int(s)
    if t == "float":
        return float(s)
    if t == "bool":
        return s == "True"
    return s


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

    # Build CSV block with explicit _i index column
    csv_text = ""
    if csv_keys:
        rows = [
            [str(i)] + [_encode_cell(cols[k][i], csv_types[k]) for k in csv_keys]
            for i in range(len(records))
        ]
        csv_text = _csv_dumps(["_i"] + csv_keys, rows)

    cols_str = ";".join(f"{k}={closed[k].payload_str}" for k in closed)
    header = f"n={len(records)}|cols:{cols_str}"
    folded_text = header + ("\n" + csv_text if csv_text else "")

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
    }

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

    # Closed-form columns
    closed_vals: dict[str, list[Any]] = {}
    for k, meta in recipe.get("cols", {}).items():
        f = ColumnFold(
            meta["codec"], meta["recipe"], "", n,
            meta.get("lossless", True), meta.get("tol"),
        )
        closed_vals[k] = reconstruct_column(f)

    # CSV columns
    csv_vals: dict[str, list[Any]] = {}
    if "\n" in folded_text:
        _, csv_text = folded_text.split("\n", 1)
        csv_header, csv_rows = _csv_loads(csv_text)
        types = recipe["csv_types"]
        for ci, k in enumerate(csv_header):
            if k in types:
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
    return out


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
