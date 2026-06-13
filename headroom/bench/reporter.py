"""Reporter for headroom-bench — CSV and markdown table emitter.

Output format follows BENCHMARK-PLAN.md §5 (headline table):

    Tool           Tokens   Saved   Reversible   ms/KB
    raw            54,174     —        —           —
    headroom       11,980    78%      Yes         2.2
"""

from __future__ import annotations

import csv
import io
import logging
from typing import TextIO

from ._types import BenchResult

logger = logging.getLogger(__name__)

# CSV columns in output order
_CSV_COLUMNS = [
    "dataset",
    "category",
    "tokenizer",
    "adapter",
    "tokens_before",
    "tokens_after",
    "saved_pct",
    "chars_before",
    "chars_after",
    "latency_ms",
    "reversible",
    "error",
]


def _result_to_row(r: BenchResult) -> dict[str, str]:
    return {
        "dataset": r.dataset,
        "category": r.category,
        "tokenizer": r.tokenizer_name,
        "adapter": r.adapter,
        "tokens_before": str(r.tokens_before),
        "tokens_after": str(r.tokens_after),
        "saved_pct": f"{r.tokens_saved_pct:.1f}",
        "chars_before": str(r.chars_before),
        "chars_after": str(r.chars_after),
        "latency_ms": f"{r.latency_ms:.2f}",
        "reversible": "" if r.reversible is None else str(r.reversible),
        "error": r.error or "",
    }


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def write_csv(results: list[BenchResult], out: TextIO | None = None) -> str:
    """Write results as CSV. Returns the CSV text; also writes to *out*."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for r in results:
        writer.writerow(_result_to_row(r))
    text = buf.getvalue()
    if out is not None:
        out.write(text)
    return text


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _fmt_tokens(n: int) -> str:
    return f"{n:,}"


def _fmt_saved(pct: float, error: str | None) -> str:
    if error:
        return "err"
    return f"{pct:.0f}%" if pct != 0 else "--"


def _fmt_reversible(v: bool | None) -> str:
    if v is None:
        return "--"
    return "Yes" if v else "No"


def _fmt_latency(ms: float, adapter: str) -> str:
    if adapter == "raw":
        return "--"
    return f"{ms:.1f}"


def write_markdown(
    results: list[BenchResult],
    out: TextIO | None = None,
) -> str:
    """Write results as a markdown table grouped by dataset+tokenizer.

    Returns the markdown text; also writes to *out* if provided.
    """
    lines: list[str] = []

    # Group by (dataset, tokenizer)
    groups: dict[tuple[str, str], list[BenchResult]] = {}
    for r in results:
        key = (r.dataset, r.tokenizer_name)
        groups.setdefault(key, []).append(r)

    for (ds, tok), group in groups.items():
        cat = group[0].category
        lines.append(f"### {ds} (category={cat}, tokenizer={tok})")
        lines.append("")
        lines.append(
            f"{'Tool':<22} {'Tokens':>8} {'Saved':>7} "
            f"{'Reversible':>11} {'ms/KB':>7}"
        )
        lines.append(
            f"{'-' * 22} {'-' * 8} {'-' * 7} "
            f"{'-' * 11} {'-' * 7}"
        )

        for r in group:
            ms_per_kb = (
                r.latency_ms / (r.chars_before / 1024)
                if r.chars_before > 0 and r.adapter != "raw"
                else 0.0
            )
            lines.append(
                f"{r.adapter:<22} "
                f"{_fmt_tokens(r.tokens_after):>8} "
                f"{_fmt_saved(r.tokens_saved_pct, r.error):>7} "
                f"{_fmt_reversible(r.reversible):>11} "
                f"{_fmt_latency(ms_per_kb, r.adapter):>7}"
            )

            if r.error:
                lines.append(f"  > error: {r.error}")

        lines.append("")

    text = "\n".join(lines)
    if out is not None:
        out.write(text)
    return text
