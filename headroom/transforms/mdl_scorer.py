"""MDL-based compressor scoring for the ContentRouter.

Generalises NumericFold's per-column MDL principle (minimise
``L(model) + L(data|model)``) to the top-level routing decision.
Instead of a hard-coded ``ContentType -> Strategy`` map, this module
lets the router *try* each candidate compressor and pick the one
whose output has the shortest description length.

Usage::

    from headroom.transforms.mdl_scorer import mdl_select

    best = mdl_select(
        content="[{...}, ...]",
        candidates=[smart_crusher, code_compressor, kompress],
        tokenizer=tokenizer,
    )
    # best.strategy, best.compressed, best.score

The scorer is opt-in — the default ContentRouter continues to use
rule-based routing unless MDL scoring is explicitly enabled.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


class Compressor(Protocol):
    """Minimal interface a compressor must satisfy for MDL scoring."""

    def compress(self, content: str, **kwargs: Any) -> str: ...


@dataclass
class MDLCandidate:
    """A candidate compressor with its MDL score."""

    name: str
    compressed: str
    model_cost: int  # L(model): overhead of the compressor itself
    data_cost: int  # L(data|model): tokens in the compressed output
    total_cost: int  # model_cost + data_cost
    latency_ms: float = 0.0
    error: str | None = None


@dataclass
class MDLResult:
    """Result of MDL-based compressor selection."""

    best: MDLCandidate
    candidates: list[MDLCandidate]
    original_tokens: int


# ---------------------------------------------------------------------------
# Model cost estimates (L(model))
# ---------------------------------------------------------------------------

# Each compressor has an inherent "description cost" — the overhead of
# its codec/format that the reader must understand. A codec legend
# (AFFINE, CONST, etc.) costs tokens even if the data is tiny. These
# estimates are calibrated in tokens.
_DEFAULT_MODEL_COSTS: dict[str, int] = {
    "raw": 0,  # no overhead
    "smart_crusher": 5,  # schema header
    "code_compressor": 10,  # AST outline format
    "kompress": 3,  # prose summarization
    "numeric_fold": 15,  # codec legend (AFFINE/CONST/POLY...)
    "columnar_fold": 20,  # codec legend + CSV header
    "log_compressor": 5,  # grouped format
    "search_compressor": 5,  # filtered results
    "diff_compressor": 3,  # patch format
    "html_extractor": 5,  # extracted content
}


def estimate_model_cost(compressor_name: str) -> int:
    """Estimate L(model) for a named compressor."""
    return _DEFAULT_MODEL_COSTS.get(compressor_name, 10)


# ---------------------------------------------------------------------------
# MDL selection
# ---------------------------------------------------------------------------


def mdl_score(
    content: str,
    compressor_name: str,
    compress_fn: Callable[[str], str],
    token_count_fn: Callable[[str], int],
    model_cost: int | None = None,
) -> MDLCandidate:
    """Score a single compressor on content using MDL.

    Args:
        content: Raw content to compress.
        compressor_name: Name of the compressor.
        compress_fn: Function that compresses content -> compressed text.
        token_count_fn: Function that counts tokens in text.
        model_cost: Override for L(model). Uses default if None.

    Returns:
        MDLCandidate with the score.
    """
    mc = model_cost if model_cost is not None else estimate_model_cost(compressor_name)

    t0 = time.perf_counter()
    try:
        compressed = compress_fn(content)
        elapsed = (time.perf_counter() - t0) * 1000
        data_cost = token_count_fn(compressed)
        return MDLCandidate(
            name=compressor_name,
            compressed=compressed,
            model_cost=mc,
            data_cost=data_cost,
            total_cost=mc + data_cost,
            latency_ms=elapsed,
        )
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        # On error, score as infinitely expensive (won't be selected)
        original_tokens = token_count_fn(content)
        return MDLCandidate(
            name=compressor_name,
            compressed=content,
            model_cost=mc,
            data_cost=original_tokens,
            total_cost=mc + original_tokens,
            latency_ms=elapsed,
            error=f"{type(e).__name__}: {e}",
        )


def mdl_select(
    content: str,
    candidates: list[tuple[str, Callable[[str], str]]],
    token_count_fn: Callable[[str], int],
    model_costs: dict[str, int] | None = None,
) -> MDLResult:
    """Select the best compressor for content using MDL.

    Always includes "raw" (identity) as a baseline candidate so we
    never pick a compressor that inflates the content.

    Args:
        content: Raw content to compress.
        candidates: List of (name, compress_fn) tuples.
        token_count_fn: Function that counts tokens in text.
        model_costs: Optional override for per-compressor model costs.

    Returns:
        MDLResult with the best candidate and all scores.
    """
    costs = model_costs or {}
    original_tokens = token_count_fn(content)

    # Always include raw as baseline
    scored: list[MDLCandidate] = [
        MDLCandidate(
            name="raw",
            compressed=content,
            model_cost=0,
            data_cost=original_tokens,
            total_cost=original_tokens,
        )
    ]

    for name, compress_fn in candidates:
        mc = costs.get(name)
        candidate = mdl_score(content, name, compress_fn, token_count_fn, mc)
        scored.append(candidate)

    # Pick the candidate with lowest total MDL cost
    best = min(scored, key=lambda c: c.total_cost)

    return MDLResult(
        best=best,
        candidates=scored,
        original_tokens=original_tokens,
    )
