"""Dataset loader for headroom-bench.

Provides built-in workload generators (SRE logs, geo search, metrics
timeseries, adversarial) and a file-based loader for custom datasets.
Generators follow the pattern established in fidelity_harness.py.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from ._types import Dataset

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in workload generators
# ---------------------------------------------------------------------------

_RNG = random.Random(42)


def _gen_logs(n: int = 200) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """SRE incident logs — affine timestamps, random latencies."""
    base = 1_718_200_000
    recs = [
        {
            "id": i,
            "ts": base + 7 * i,
            "level": _RNG.choice(["INFO", "WARN", "ERROR"]),
            "latency_ms": round(_RNG.gauss(45, 9), 1),
            "msg": _RNG.choice(["request handled", "cache miss", "retry scheduled"]),
        }
        for i in range(n)
    ]
    return {"results": recs}, recs


def _gen_geo(n: int = 150) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Geo search results — constant lat/lng, affine alt."""
    recs = [
        {
            "id": 5000 + i,
            "lat": 37.7749,
            "lng": -122.4194,
            "alt": 12 + 3 * i,
            "name": f"sensor-{i}",
        }
        for i in range(n)
    ]
    return {"results": recs}, recs


def _gen_metrics(n: int = 300) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """API metrics timeseries — quadratic count, constant share."""
    recs = [
        {
            "t": i,
            "count": i * i + 2 * i,
            "p99": round(_RNG.uniform(80, 95), 2),
            "share": 0.2,
        }
        for i in range(n)
    ]
    return {"data": recs}, recs


def _gen_adversarial(n: int = 60) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Random high-entropy floats — must NOT be falsely compressed."""
    recs = [
        {
            "id": i,
            "value": _RNG.random() * 1000,
            "noise": _RNG.gauss(0, 1),
        }
        for i in range(n)
    ]
    return {"results": recs}, recs


# ---------------------------------------------------------------------------
# Agent workload generators (README's four workloads)
# ---------------------------------------------------------------------------


def _gen_code_search(n: int = 80) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Code search / grep results — file paths, line numbers, snippets."""
    files = [
        "src/auth/login.py", "src/auth/session.py", "src/api/routes.py",
        "src/api/middleware.py", "src/db/models.py", "src/db/queries.py",
        "src/utils/helpers.py", "src/utils/cache.py", "tests/test_auth.py",
        "tests/test_api.py", "lib/config.ts", "lib/hooks.ts",
    ]
    snippets = [
        "def authenticate(user, password):",
        "session.verify_token(token)",
        "return JsonResponse(data, status=200)",
        "raise PermissionError('unauthorized')",
        "query = db.select(User).where(id=uid)",
        "cache.set(key, value, ttl=300)",
        "assert response.status_code == 200",
        "import { useAuth } from './hooks'",
    ]
    recs = [
        {
            "file": _RNG.choice(files),
            "line": _RNG.randint(1, 500),
            "col": _RNG.randint(1, 80),
            "snippet": _RNG.choice(snippets),
            "score": round(_RNG.uniform(0.5, 1.0), 4),
        }
        for i in range(n)
    ]
    return {"matches": recs}, recs


def _gen_github_issues(n: int = 100) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """GitHub issue triage — issue metadata with numeric fields."""
    labels = ["bug", "feature", "docs", "perf", "security", "chore"]
    states = ["open", "closed"]
    recs = [
        {
            "number": 1000 + i,
            "title": f"Issue #{1000 + i}: {_RNG.choice(['Fix', 'Add', 'Update', 'Remove'])} "
                     f"{_RNG.choice(['auth', 'cache', 'API', 'UI', 'DB', 'tests'])}",
            "state": _RNG.choice(states),
            "labels": [_RNG.choice(labels)],
            "comments": _RNG.randint(0, 50),
            "reactions": _RNG.randint(0, 20),
            "created_at": f"2026-{_RNG.randint(1, 6):02d}-{_RNG.randint(1, 28):02d}",
            "closed_at": f"2026-{_RNG.randint(1, 6):02d}-{_RNG.randint(1, 28):02d}"
                         if _RNG.random() > 0.4 else None,
        }
        for i in range(n)
    ]
    return {"issues": recs}, recs


def _gen_codebase_exploration(n: int = 120) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Codebase exploration — file tree with sizes, line counts, types."""
    extensions = [".py", ".ts", ".js", ".go", ".rs", ".md", ".json", ".yaml"]
    dirs = [
        "src/", "src/api/", "src/auth/", "src/db/", "src/utils/",
        "tests/", "lib/", "docs/", "scripts/", "config/",
    ]
    recs = [
        {
            "path": f"{_RNG.choice(dirs)}{_RNG.choice(['main', 'index', 'utils', 'helpers', 'config', 'test_' + str(i)])}{_RNG.choice(extensions)}",
            "size_bytes": _RNG.randint(100, 50000),
            "lines": _RNG.randint(10, 2000),
            "last_modified": f"2026-{_RNG.randint(1, 6):02d}-{_RNG.randint(1, 28):02d}",
            "language": _RNG.choice(["python", "typescript", "go", "rust", "markdown"]),
        }
        for i in range(n)
    ]
    return {"files": recs}, recs


# ---------------------------------------------------------------------------
# Numeric-heavy generators (the fork's home turf)
# ---------------------------------------------------------------------------


def _gen_api_response(n: int = 200) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """API/metrics response — dense numeric columns, typical dashboard data."""
    recs = [
        {
            "endpoint": _RNG.choice(["/api/users", "/api/orders", "/api/health", "/api/search"]),
            "timestamp": 1718200000 + 60 * i,
            "requests": 1000 + i * 5,
            "errors": _RNG.randint(0, 10),
            "p50_ms": round(12.0 + _RNG.gauss(0, 2), 2),
            "p95_ms": round(45.0 + _RNG.gauss(0, 5), 2),
            "p99_ms": round(120.0 + _RNG.gauss(0, 15), 2),
            "cpu_pct": round(_RNG.uniform(20, 80), 1),
            "mem_mb": round(512 + _RNG.gauss(0, 30), 1),
        }
        for i in range(n)
    ]
    return {"data": recs}, recs


def _gen_embeddings(n: int = 100) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Embedding/score arrays — high-dimensional numeric data."""
    recs = [
        {
            "id": f"doc-{i}",
            "score": round(_RNG.uniform(0.0, 1.0), 6),
            "embedding": [round(_RNG.gauss(0, 1), 4) for _ in range(8)],
            "rank": i + 1,
            "tokens": _RNG.randint(50, 500),
        }
        for i in range(n)
    ]
    return {"results": recs}, recs


def _gen_timeseries(n: int = 250) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Dense timeseries — monotonic timestamps, polynomial trends."""
    base_t = 1718200000
    recs = [
        {
            "t": base_t + i,
            "value": round(100 + 0.5 * i + 0.001 * i * i + _RNG.gauss(0, 3), 3),
            "min": round(90 + 0.4 * i, 2),
            "max": round(110 + 0.6 * i, 2),
            "count": 1000 + 10 * i,
        }
        for i in range(n)
    ]
    return {"series": recs}, recs


# ---------------------------------------------------------------------------
# Recurrence-pattern generators (trace-unit motivated)
# ---------------------------------------------------------------------------


def _gen_recurrence(n: int = 100) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Records with columns following linear recurrences.

    These sequences arise naturally from algebraic trace constructions
    (e.g. Tr(theta * u^r) for algebraic units u). Current AFFINE/POLY
    codecs miss them; the RECURRENCE codec captures them exactly.
    """
    # Fibonacci-like: T_r = 4*T_{r-1} - T_{r-2}
    fib = [1, 3]
    for _ in range(n - 2):
        fib.append(4 * fib[-1] - fib[-2])

    # Lucas-like: T_r = T_{r-1} + T_{r-2}
    luc = [2, 1]
    for _ in range(n - 2):
        luc.append(luc[-1] + luc[-2])

    # Exponential: T_r = 3 * T_{r-1}
    exp_col = [1]
    for _ in range(n - 1):
        exp_col.append(3 * exp_col[-1])

    recs = [
        {
            "index": i,
            "fib_like": fib[i],
            "lucas_like": luc[i],
            "exponential": exp_col[i],
            "label": _RNG.choice(["A", "B", "C"]),
        }
        for i in range(n)
    ]
    return {"results": recs}, recs


# ---------------------------------------------------------------------------
# Cross-column generators (derived columns)
# ---------------------------------------------------------------------------


def _gen_cross_column(n: int = 120) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Records where several columns are exact affine functions of others.

    Common in real tool output: dual-unit timestamps, byte/KiB pairs,
    price-with-tax, duplicated id columns. The ColumnarFold cross-column
    codec stores each derived column as a one-line reference instead of N
    rows of data. The base columns are deliberately irregular (random walk)
    so per-column codecs can't shrink the derived columns on their own.
    """
    recs = []
    blocks = 8
    sec = 1718200000
    for i in range(n):
        blocks = max(1, blocks + _RNG.randint(-3, 6))
        bytes_v = blocks * 1024  # block-aligned so the byte/KiB relation is exact
        sec += _RNG.randint(1, 900)
        price = round(_RNG.uniform(1, 999), 2)
        recs.append({
            "id": 10_000 + i,
            "owner_id": 10_000 + i,            # exact duplicate of id
            "sec": sec,
            "ms": sec * 1000,                  # dual-unit timestamp
            "bytes": bytes_v,
            "kib": bytes_v / 1024,             # byte/KiB pair (float)
            "price": price,
            "price_tax": round(price + 7, 2),  # price + fixed fee
            "status": _RNG.choice(["ok", "warn", "error"]),
        })
    return {"results": recs}, recs


# ---------------------------------------------------------------------------
# Adversarial generators (robustness)
# ---------------------------------------------------------------------------


def _gen_near_progression(n: int = 80) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Near-but-not-quite arithmetic progression — must not be falsely folded."""
    recs = [
        {
            "id": i,
            "value": 100 + 5 * i + (0.01 if i == n // 2 else 0),  # one perturbation
            "other": round(_RNG.uniform(0, 100), 2),
        }
        for i in range(n)
    ]
    return {"results": recs}, recs


def _gen_mixed_types(n: int = 60) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Mixed-type columns — some rows have strings where others have numbers."""
    recs = []
    for i in range(n):
        rec: dict[str, Any] = {"id": i}
        if i % 10 == 0:
            rec["value"] = "N/A"
            rec["score"] = None
        else:
            rec["value"] = _RNG.randint(1, 1000)
            rec["score"] = round(_RNG.uniform(0, 1), 4)
        rec["label"] = _RNG.choice(["A", "B", "C"])
        recs.append(rec)
    return {"results": recs}, recs


# ---------------------------------------------------------------------------
# Generator registry and suite definitions
# ---------------------------------------------------------------------------

_GENERATORS: dict[str, tuple[str, Any]] = {
    # Original numeric workloads
    "sre_logs": ("numeric", _gen_logs),
    "geo_search": ("numeric", _gen_geo),
    "metrics_timeseries": ("numeric", _gen_metrics),
    # Agent workloads (README's proof table)
    "code_search": ("agent", _gen_code_search),
    "github_issues": ("agent", _gen_github_issues),
    "codebase_exploration": ("agent", _gen_codebase_exploration),
    # Numeric-heavy (fork differentiator)
    "api_response": ("numeric-heavy", _gen_api_response),
    "embeddings": ("numeric-heavy", _gen_embeddings),
    "timeseries": ("numeric-heavy", _gen_timeseries),
    # Recurrence-pattern data (trace-unit sequences)
    "recurrence_sequences": ("recurrence", _gen_recurrence),
    # Cross-column data (derived columns)
    "cross_column": ("cross-column", _gen_cross_column),
    # Adversarial (robustness)
    "adversarial_floats": ("adversarial", _gen_adversarial),
    "near_progression": ("adversarial", _gen_near_progression),
    "mixed_types": ("adversarial", _gen_mixed_types),
}

# Suite -> dataset names
SUITES: dict[str, list[str]] = {
    "numeric": ["sre_logs", "geo_search", "metrics_timeseries"],
    "agent": ["code_search", "github_issues", "codebase_exploration"],
    "numeric-heavy": ["api_response", "embeddings", "timeseries"],
    "recurrence": ["recurrence_sequences"],
    "cross-column": ["cross_column"],
    "adversarial": ["adversarial_floats", "near_progression", "mixed_types"],
    "all": list(_GENERATORS.keys()),
}


def load_builtin(name: str) -> Dataset:
    """Load a built-in dataset by name.

    The RNG is re-seeded per dataset so results are deterministic
    regardless of call order.
    """
    if name not in _GENERATORS:
        raise ValueError(
            f"Unknown dataset {name!r}; available: {sorted(_GENERATORS)}"
        )
    category, gen_fn = _GENERATORS[name]
    # Re-seed so each dataset is independent and reproducible
    _RNG.seed(hash(name) & 0xFFFF_FFFF)
    obj, recs = gen_fn()
    raw = json.dumps(obj, separators=(",", ":"))
    return Dataset(name=name, category=category, raw_json=raw, records=recs)


def load_suite(suite: str) -> list[Dataset]:
    """Load all datasets for a named suite."""
    if suite not in SUITES:
        raise ValueError(
            f"Unknown suite {suite!r}; available: {sorted(SUITES)}"
        )
    return [load_builtin(name) for name in SUITES[suite]]


def load_file(path: str | Path) -> Dataset:
    """Load a dataset from a JSON file.

    The file must contain a JSON object with an array field (e.g. "results"
    or "data"). The first array field found is used as the record list.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    obj = json.loads(raw)
    # find the first list-of-dicts field
    records: list[dict[str, Any]] = []
    if isinstance(obj, list):
        records = obj
    elif isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                records = v
                break
    return Dataset(
        name=p.stem,
        category="custom",
        raw_json=json.dumps(obj, separators=(",", ":")),
        records=records,
    )
