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


_GENERATORS: dict[str, tuple[str, Any]] = {
    "sre_logs": ("numeric", _gen_logs),
    "geo_search": ("numeric", _gen_geo),
    "metrics_timeseries": ("numeric", _gen_metrics),
    "adversarial_floats": ("adversarial", _gen_adversarial),
}

# Suite -> dataset names
SUITES: dict[str, list[str]] = {
    "numeric": ["sre_logs", "geo_search", "metrics_timeseries"],
    "adversarial": ["adversarial_floats"],
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
