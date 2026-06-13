"""Shared data types for headroom-bench."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Dataset:
    """A benchmark dataset: a list of JSON records with metadata."""

    name: str
    category: str  # e.g. "numeric", "agent", "adversarial"
    raw_json: str  # compact JSON text (the "context" to compress)
    records: list[dict[str, Any]]
    checksum: str = ""

    def __post_init__(self) -> None:
        if not self.checksum:
            self.checksum = hashlib.sha256(self.raw_json.encode()).hexdigest()[:16]


@dataclass
class CompressedOutput:
    """Result of running one adapter on one dataset."""

    adapter_name: str
    text: str  # compressed text (or original for raw)
    tokens_before: int = 0
    tokens_after: int = 0
    chars_before: int = 0
    chars_after: int = 0
    latency_ms: float = 0.0
    reversible: bool | None = None  # None = not measured
    error: str | None = None  # non-None if adapter failed gracefully


@dataclass
class BenchResult:
    """Scored result for one (adapter, dataset, tokenizer) triple."""

    adapter: str
    dataset: str
    category: str
    tokenizer_name: str
    tokens_before: int
    tokens_after: int
    tokens_saved_pct: float
    chars_before: int
    chars_after: int
    latency_ms: float
    reversible: bool | None
    error: str | None = None


@dataclass
class SuiteConfig:
    """Configuration for a benchmark run."""

    suites: list[str] = field(default_factory=lambda: ["all"])
    tokenizers: list[str] = field(default_factory=lambda: ["cl100k_base"])
    output_csv: str | None = None
    output_md: str | None = None
    verbose: bool = False
