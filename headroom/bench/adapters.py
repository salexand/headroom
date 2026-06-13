"""Compression tool adapters for headroom-bench.

Each adapter wraps a compression tool behind a uniform interface:
``compress(context: str) -> CompressedOutput``. Adapters that depend on
missing packages degrade gracefully (return an error result, never raise).

Competitors (RTK, lean-ctx, upstream Headroom) are auto-detected at
import time and included in ``get_adapters()`` only when available.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import subprocess
import tempfile
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
# columnar-fold — ColumnarFold adapter (NumericFold + CSV key dedup)
# ---------------------------------------------------------------------------


class ColumnarFoldAdapter:
    """ColumnarFold — NumericFold codecs + CSV transposition for residuals.

    Saves more than NumericFold alone on data with non-numeric columns
    by deduplicating column keys via CSV header.
    """

    name: str = "columnar-fold"

    def compress(self, context: str) -> CompressedOutput:
        t0 = time.perf_counter()
        try:
            from ..transforms.columnar_fold import columnar_fold

            result = columnar_fold(context)

            if result is None:
                elapsed = (time.perf_counter() - t0) * 1000
                return CompressedOutput(
                    adapter_name=self.name,
                    text=context,
                    chars_before=len(context),
                    chars_after=len(context),
                    latency_ms=elapsed,
                    reversible=True,
                )

            elapsed = (time.perf_counter() - t0) * 1000
            return CompressedOutput(
                adapter_name=self.name,
                text=result.folded_text,
                chars_before=len(context),
                chars_after=len(result.folded_text),
                latency_ms=elapsed,
                reversible=True,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug("ColumnarFoldAdapter failed: %s", e)
            return CompressedOutput(
                adapter_name=self.name,
                text=context,
                chars_before=len(context),
                chars_after=len(context),
                latency_ms=elapsed,
                error=f"{type(e).__name__}: {e}",
            )


# ---------------------------------------------------------------------------
# RTK — CLI command-output rewriting (subprocess)
# ---------------------------------------------------------------------------


def _rtk_available() -> bool:
    return shutil.which("rtk") is not None


class RTKAdapter:
    """RTK (Reduce Toolkit) — CLI proxy that filters/summarises output.

    RTK operates on files, so we write the context to a temp file and
    invoke ``rtk json <file>``.  Falls back gracefully if the ``rtk``
    binary is not installed (``pip install rtk-py``).
    """

    name: str = "rtk"

    def compress(self, context: str) -> CompressedOutput:
        if not _rtk_available():
            return CompressedOutput(
                adapter_name=self.name,
                text=context,
                chars_before=len(context),
                chars_after=len(context),
                error="rtk binary not found (pip install rtk-py)",
            )

        t0 = time.perf_counter()
        try:
            # RTK's json subcommand reads from a file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8",
            ) as f:
                f.write(context)
                tmp_path = f.name
            try:
                proc = subprocess.run(
                    ["rtk", "json", tmp_path],
                    capture_output=True, text=True, timeout=30,
                )
                compressed = proc.stdout
                # Strip the "[rtk]" banner line if present
                lines = compressed.splitlines(keepends=True)
                if lines and lines[0].startswith("[rtk]"):
                    compressed = "".join(lines[1:])
            finally:
                os.unlink(tmp_path)

            elapsed = (time.perf_counter() - t0) * 1000
            return CompressedOutput(
                adapter_name=self.name,
                text=compressed,
                chars_before=len(context),
                chars_after=len(compressed),
                latency_ms=elapsed,
                reversible=False,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug("RTKAdapter failed: %s", e)
            return CompressedOutput(
                adapter_name=self.name,
                text=context,
                chars_before=len(context),
                chars_after=len(context),
                latency_ms=elapsed,
                error=f"{type(e).__name__}: {e}",
            )


# ---------------------------------------------------------------------------
# lean-ctx — context compression middleware (leanctx Python SDK)
# ---------------------------------------------------------------------------


def _leanctx_available() -> bool:
    try:
        import leanctx  # noqa: F401

        return True
    except ImportError:
        return False


class LeanCtxAdapter:
    """lean-ctx compression via the ``leanctx`` Python SDK.

    Uses the Middleware with ``mode=on`` which routes through available
    compressors (Verbatim by default, Lingua/SelfLLM if configured).
    Falls back gracefully if ``leanctx`` is not installed.
    """

    name: str = "lean-ctx"

    def compress(self, context: str) -> CompressedOutput:
        if not _leanctx_available():
            return CompressedOutput(
                adapter_name=self.name,
                text=context,
                chars_before=len(context),
                chars_after=len(context),
                error="leanctx not installed (pip install leanctx)",
            )

        t0 = time.perf_counter()
        try:
            from leanctx import Middleware

            mw = Middleware({"mode": "on"})
            messages = [{"role": "user", "content": context}]
            result, stats = mw.compress_messages(messages)
            compressed = result[0]["content"]

            elapsed = (time.perf_counter() - t0) * 1000
            return CompressedOutput(
                adapter_name=self.name,
                text=compressed,
                chars_before=len(context),
                chars_after=len(compressed),
                latency_ms=elapsed,
                reversible=False,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug("LeanCtxAdapter failed: %s", e)
            return CompressedOutput(
                adapter_name=self.name,
                text=context,
                chars_before=len(context),
                chars_after=len(context),
                latency_ms=elapsed,
                error=f"{type(e).__name__}: {e}",
            )


# ---------------------------------------------------------------------------
# headroom-upstream — parent fork without NumericFold
# ---------------------------------------------------------------------------


class HeadroomUpstreamAdapter:
    """Headroom upstream (chopratejas/main) — pipeline without NumericFold.

    Simulates the parent fork by running the same TransformPipeline but
    with NumericFold disabled. This isolates the fork's added value:
    any savings difference between ``headroom`` and ``headroom-upstream``
    is attributable to NumericFold.
    """

    name: str = "headroom-upstream"

    def compress(self, context: str) -> CompressedOutput:
        t0 = time.perf_counter()
        try:
            from ..config import HeadroomConfig
            from ..providers.anthropic import AnthropicProvider
            from ..transforms.pipeline import TransformPipeline

            model = "claude-sonnet-4-20250514"
            config = HeadroomConfig()
            # Ensure NumericFold is disabled to simulate upstream
            config.numeric_fold_enabled = False
            provider = AnthropicProvider(warn=False)

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

            # Also unset the env var to be sure
            old_env = os.environ.pop("HEADROOM_NUMERIC_FOLD", None)
            try:
                pipeline = TransformPipeline(config=config, provider=provider)
                result = pipeline.apply(messages, model, model_limit=200_000)
            finally:
                if old_env is not None:
                    os.environ["HEADROOM_NUMERIC_FOLD"] = old_env

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
            logger.debug("HeadroomUpstreamAdapter failed: %s", e)
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
    ColumnarFoldAdapter(),
]

# Competitor adapters with their availability checks
_COMPETITOR_SPECS: list[tuple[type, Any]] = [
    (RTKAdapter, _rtk_available),
    (LeanCtxAdapter, _leanctx_available),
]


def get_adapters(
    include_pipeline: bool = False,
    include_competitors: bool = False,
    include_unavailable: bool = False,
) -> list[Adapter]:
    """Return the list of available adapters.

    By default returns only fast, self-contained adapters (raw, gzip,
    numeric-fold).

    *include_pipeline*: add the full Headroom pipeline adapter and the
    upstream (no-NumericFold) variant. Slower — loads ContentRouter, etc.

    *include_competitors*: add competitor adapters (RTK, lean-ctx) when
    their packages are installed. Missing tools degrade gracefully.

    *include_unavailable*: show stubs for all tools, even missing ones
    (useful for table layout).
    """
    adapters: list[Adapter] = list(_FAST_ADAPTERS)

    if include_competitors or include_unavailable:
        for cls, check_fn in _COMPETITOR_SPECS:
            if include_unavailable or check_fn():
                adapters.append(cls())
            elif include_competitors:
                # Available was requested but tool is missing — show stub
                adapters.append(UnavailableAdapter(cls.name))

    if include_pipeline or include_unavailable:
        adapters.append(HeadroomUpstreamAdapter())
        adapters.append(HeadroomAdapter())

    return adapters
