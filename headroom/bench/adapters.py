"""Compression tool adapters for headroom-bench.

Each adapter wraps a compression tool behind a uniform interface:
``compress(context: str) -> CompressedOutput``. Adapters that depend on
missing packages degrade gracefully (return an error result, never raise).
"""

from __future__ import annotations

import gzip
import logging
import time
from typing import Any, Protocol

from ._types import CompressedOutput

logger = logging.getLogger(__name__)


class Adapter(Protocol):
    """Protocol for compression adapters."""

    name: str

    def compress(self, context: str) -> CompressedOutput: ...


# ---------------------------------------------------------------------------
# raw — identity baseline (the denominator)
# ---------------------------------------------------------------------------


class RawAdapter:
    """No compression — returns the context unchanged."""

    name: str = "raw"

    def compress(self, context: str) -> CompressedOutput:
        return CompressedOutput(
            adapter_name=self.name,
            text=context,
            chars_before=len(context),
            chars_after=len(context),
            latency_ms=0.0,
            reversible=True,
        )


# ---------------------------------------------------------------------------
# gzip — byte-compression reference (storage only, not token reduction)
# ---------------------------------------------------------------------------


class GzipAdapter:
    """gzip byte compression — included to distinguish bytes from tokens."""

    name: str = "gzip"

    def compress(self, context: str) -> CompressedOutput:
        raw_bytes = context.encode("utf-8")
        t0 = time.perf_counter()
        compressed = gzip.compress(raw_bytes)
        elapsed = (time.perf_counter() - t0) * 1000
        return CompressedOutput(
            adapter_name=self.name,
            text=context,  # text unchanged (gzip is storage-only)
            chars_before=len(raw_bytes),
            chars_after=len(compressed),
            latency_ms=elapsed,
            reversible=True,
        )


# ---------------------------------------------------------------------------
# headroom — this fork's transform pipeline
# ---------------------------------------------------------------------------


class HeadroomAdapter:
    """This fork's compression pipeline (ContentRouter + NumericFold)."""

    name: str = "headroom"

    def compress(self, context: str) -> CompressedOutput:
        t0 = time.perf_counter()
        try:
            from ..config import HeadroomConfig
            from ..providers.anthropic import AnthropicProvider
            from ..transforms.pipeline import TransformPipeline

            model = "claude-sonnet-4-20250514"
            config = HeadroomConfig()
            provider = AnthropicProvider(warn=False)

            # Build a minimal message list with the context as a tool result
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": "process this"},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "bench_call",
                            "name": "bench_tool",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_use_id": "bench_call",
                    "content": context,
                },
            ]

            pipeline = TransformPipeline(config=config, provider=provider)
            result: TransformResult = pipeline.apply(
                messages, model, model_limit=200_000,
            )

            # Extract the compressed tool content
            compressed_text = context
            for msg in result.messages:
                if msg.get("role") == "tool":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        compressed_text = content
                    break

            elapsed = (time.perf_counter() - t0) * 1000
            return CompressedOutput(
                adapter_name=self.name,
                text=compressed_text,
                chars_before=len(context),
                chars_after=len(compressed_text),
                tokens_before=result.tokens_before,
                tokens_after=result.tokens_after,
                latency_ms=elapsed,
                reversible=True,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug("HeadroomAdapter failed: %s", e)
            return CompressedOutput(
                adapter_name=self.name,
                text=context,
                chars_before=len(context),
                chars_after=len(context),
                latency_ms=elapsed,
                error=f"{type(e).__name__}: {e}",
            )


# ---------------------------------------------------------------------------
# numeric-fold — direct NumericFold adapter (the fork's differentiator)
# ---------------------------------------------------------------------------


class NumericFoldAdapter:
    """Direct NumericFold compression, bypassing the full pipeline.

    This isolates the fork's key contribution so it can be measured
    independently of ContentRouter / SmartCrusher.
    """

    name: str = "numeric-fold"

    def compress(self, context: str) -> CompressedOutput:
        t0 = time.perf_counter()
        try:
            from ..transforms.numeric_fold import NumericFoldConfig, fold_tool_output

            cfg = NumericFoldConfig()
            result = fold_tool_output(context, cfg)

            if result is None:
                # Nothing foldable — return unchanged
                elapsed = (time.perf_counter() - t0) * 1000
                return CompressedOutput(
                    adapter_name=self.name,
                    text=context,
                    chars_before=len(context),
                    chars_after=len(context),
                    latency_ms=elapsed,
                    reversible=True,
                )

            folded_text, _recipe = result
            elapsed = (time.perf_counter() - t0) * 1000
            return CompressedOutput(
                adapter_name=self.name,
                text=folded_text,
                chars_before=len(context),
                chars_after=len(folded_text),
                latency_ms=elapsed,
                reversible=True,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug("NumericFoldAdapter failed: %s", e)
            return CompressedOutput(
                adapter_name=self.name,
                text=context,
                chars_before=len(context),
                chars_after=len(context),
                latency_ms=elapsed,
                error=f"{type(e).__name__}: {e}",
            )


# ---------------------------------------------------------------------------
# Unavailable adapter stub — for competitors not yet wired
# ---------------------------------------------------------------------------


class UnavailableAdapter:
    """Placeholder for tools not yet integrated (RTK, lean-ctx, upstream)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def compress(self, context: str) -> CompressedOutput:
        return CompressedOutput(
            adapter_name=self.name,
            text=context,
            chars_before=len(context),
            chars_after=len(context),
            error="adapter not available",
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_FAST_ADAPTERS: list[Adapter] = [
    RawAdapter(),
    GzipAdapter(),
    NumericFoldAdapter(),
]


def get_adapters(
    include_pipeline: bool = False,
    include_unavailable: bool = False,
) -> list[Adapter]:
    """Return the list of available adapters.

    By default returns only fast, self-contained adapters (raw, gzip,
    numeric-fold).  Set *include_pipeline* to add the full Headroom
    pipeline adapter (slower — loads ContentRouter, SmartCrusher, etc.).
    Set *include_unavailable* for placeholder stubs of competitors not
    yet integrated (useful for table layout).
    """
    adapters: list[Adapter] = list(_FAST_ADAPTERS)
    if include_pipeline:
        adapters.append(HeadroomAdapter())
    if include_unavailable:
        for name in ("rtk", "lean-ctx", "headroom-upstream"):
            adapters.append(UnavailableAdapter(name))
    return adapters
