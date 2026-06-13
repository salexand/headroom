"""Reporter for headroom-bench — CSV, markdown, and coverage heatmap.

Output formats follow BENCHMARK-PLAN.md:
  §5  Headline table (per-dataset + aggregate)
  §5  Content-type coverage heatmap (tools x categories)
  §6  Fairness header (commit hash, tool versions, tokenizer)
"""

from __future__ import annotations

import csv
import io
import logging
import subprocess
from collections import defaultdict
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

    # Aggregate headline table
    agg = _aggregate_results(results)
    if agg:
        lines.append("### AGGREGATE (all datasets)")
        lines.append("")
        lines.append(
            f"{'Tool':<22} {'Tokens':>8} {'Saved':>7} "
            f"{'Reversible':>11}"
        )
        lines.append(
            f"{'-' * 22} {'-' * 8} {'-' * 7} "
            f"{'-' * 11}"
        )
        for adapter, (total_before, total_after, rev) in agg.items():
            pct = 100.0 * (1 - total_after / total_before) if total_before else 0
            lines.append(
                f"{adapter:<22} "
                f"{_fmt_tokens(total_after):>8} "
                f"{f'{pct:.0f}%' if pct != 0 else '--':>7} "
                f"{_fmt_reversible(rev):>11}"
            )
        lines.append("")

    # Coverage heatmap
    heatmap = write_coverage_heatmap(results)
    if heatmap:
        lines.append(heatmap)

    text = "\n".join(lines)
    if out is not None:
        out.write(text)
    return text


def _aggregate_results(
    results: list[BenchResult],
) -> dict[str, tuple[int, int, bool | None]]:
    """Aggregate tokens across all datasets per adapter (first tokenizer only).

    Returns {adapter: (total_before, total_after, reversible)}.
    """
    if not results:
        return {}
    first_tok = results[0].tokenizer_name
    agg: dict[str, list[int | bool | None]] = {}
    for r in results:
        if r.tokenizer_name != first_tok or r.error:
            continue
        if r.adapter not in agg:
            agg[r.adapter] = [0, 0, r.reversible]
        agg[r.adapter][0] += r.tokens_before
        agg[r.adapter][1] += r.tokens_after
        # reversible = True only if ALL results for this adapter are True
        if agg[r.adapter][2] is True and r.reversible is not True:
            agg[r.adapter][2] = r.reversible
    return {k: (v[0], v[1], v[2]) for k, v in agg.items()}


# ---------------------------------------------------------------------------
# Coverage heatmap (tools x content types)
# ---------------------------------------------------------------------------


def write_coverage_heatmap(
    results: list[BenchResult],
    out: TextIO | None = None,
) -> str:
    """Generate a coverage heatmap: tools x categories, cell = %saved.

    From BENCHMARK-PLAN.md §5: "the single most persuasive artifact,
    because it shows the fork covers cells others leave on the table."
    """
    if not results:
        return ""

    first_tok = results[0].tokenizer_name
    # Build matrix: adapter -> category -> list of saved_pct values
    matrix: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    categories: set[str] = set()
    adapters_order: list[str] = []

    for r in results:
        if r.tokenizer_name != first_tok or r.error:
            continue
        categories.add(r.category)
        if r.adapter not in adapters_order:
            adapters_order.append(r.adapter)
        matrix[r.adapter][r.category].append(r.tokens_saved_pct)

    # Compute averages
    avg_matrix: dict[str, dict[str, float]] = {}
    for adapter in adapters_order:
        avg_matrix[adapter] = {}
        for cat in sorted(categories):
            vals = matrix[adapter].get(cat, [])
            avg_matrix[adapter][cat] = sum(vals) / len(vals) if vals else 0.0

    # Render
    cats = sorted(categories)
    lines: list[str] = []
    lines.append("### Coverage Heatmap (% tokens saved by category)")
    lines.append("")

    # Header
    header = f"{'Tool':<22}"
    for cat in cats:
        header += f" {cat:>14}"
    lines.append(header)

    sep = f"{'-' * 22}"
    for cat in cats:
        sep += f" {'-' * 14}"
    lines.append(sep)

    # Rows
    for adapter in adapters_order:
        row = f"{adapter:<22}"
        for cat in cats:
            val = avg_matrix[adapter].get(cat, 0.0)
            cell = f"{val:.0f}%" if val != 0 else "--"
            row += f" {cell:>14}"
        lines.append(row)

    lines.append("")

    text = "\n".join(lines)
    if out is not None:
        out.write(text)
    return text


# ---------------------------------------------------------------------------
# Fairness header
# ---------------------------------------------------------------------------


def _git_commit_hash() -> str:
    """Get the current git commit hash, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def write_fairness_header(
    results: list[BenchResult],
    out: TextIO | None = None,
) -> str:
    """Generate the fairness rules header from BENCHMARK-PLAN.md §6.

    Includes commit hash, tokenizer, adapter list, and dataset count.
    """
    if not results:
        return ""

    tokenizers = sorted({r.tokenizer_name for r in results})
    adapters = []
    seen: set[str] = set()
    for r in results:
        if r.adapter not in seen:
            adapters.append(r.adapter)
            seen.add(r.adapter)
    datasets = sorted({r.dataset for r in results})
    commit = _git_commit_hash()

    lines = [
        "## Benchmark Report",
        "",
        f"- **Commit**: `{commit}`",
        f"- **Tokenizer(s)**: {', '.join(tokenizers)}",
        f"- **Adapters**: {', '.join(adapters)}",
        f"- **Datasets**: {len(datasets)} ({', '.join(datasets)})",
        f"- **Reproduce**: `python -m headroom.bench run --suite all`",
        "",
    ]

    text = "\n".join(lines)
    if out is not None:
        out.write(text)
    return text


# ---------------------------------------------------------------------------
# Fidelity table
# ---------------------------------------------------------------------------


def write_fidelity_table(
    results: list[Any],
    out: TextIO | None = None,
) -> str:
    """Write answer-fidelity results as a markdown table.

    Each result is a FidelityResult from headroom.bench.fidelity.
    """
    if not results:
        return ""

    lines: list[str] = []
    lines.append("### Answer Fidelity (deterministic sufficiency check)")
    lines.append("")
    lines.append(
        f"{'Tool':<22} {'Dataset':<22} {'Score':>10} {'Accuracy':>10}"
    )
    lines.append(
        f"{'-' * 22} {'-' * 22} {'-' * 10} {'-' * 10}"
    )

    for r in results:
        lines.append(
            f"{r.adapter:<22} "
            f"{r.dataset:<22} "
            f"{r.correct}/{r.total:>6} "
            f"{r.accuracy:>9.0%}"
        )

    lines.append("")
    text = "\n".join(lines)
    if out is not None:
        out.write(text)
    return text
