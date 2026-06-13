"""Scorer for headroom-bench.

Measures the deterministic axes from BENCHMARK-PLAN.md:
  1. Token reduction (cl100k_base and o200k_base)
  3. Reversibility (not yet — needs CCR wiring)
  4. Latency (captured by adapters)
  5. Coverage (per content-type, aggregated by reporter)

Axis 2 (answer fidelity) requires a live LLM and is deferred.
"""

from __future__ import annotations

import logging

import tiktoken

from ._types import BenchResult, CompressedOutput, Dataset

logger = logging.getLogger(__name__)


def _count_tokens(text: str, encoding: tiktoken.Encoding) -> int:
    """Count tokens using a tiktoken encoding."""
    return len(encoding.encode(text))


def score(
    dataset: Dataset,
    output: CompressedOutput,
    tokenizer_name: str = "cl100k_base",
) -> BenchResult:
    """Score a single (adapter, dataset) result on one tokenizer.

    Token counts are computed here (not in the adapter) so that all
    adapters are measured with the same tokenizer.  The adapter's own
    ``tokens_before`` / ``tokens_after`` (which may come from the
    pipeline's internal counter) are ignored for the headline number.
    """
    enc = tiktoken.get_encoding(tokenizer_name)

    tokens_before = _count_tokens(dataset.raw_json, enc)
    tokens_after = _count_tokens(output.text, enc)
    saved_pct = (
        100.0 * (1 - tokens_after / tokens_before)
        if tokens_before > 0
        else 0.0
    )

    return BenchResult(
        adapter=output.adapter_name,
        dataset=dataset.name,
        category=dataset.category,
        tokenizer_name=tokenizer_name,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        tokens_saved_pct=round(saved_pct, 1),
        chars_before=output.chars_before,
        chars_after=output.chars_after,
        latency_ms=round(output.latency_ms, 2),
        reversible=output.reversible,
        error=output.error,
    )
