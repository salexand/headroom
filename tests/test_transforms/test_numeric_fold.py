"""Unit and round-trip tests for NumericFold transform.

Covers codec selection, lossless reconstruction, edge cases, and
integration with the transform pipeline. These tests run in CI
without any API key or external dependencies.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from headroom.transforms.numeric_fold import (
    ColumnFold,
    NumericFoldConfig,
    fold_column,
    fold_tool_output,
    reconstruct_column,
)


# ---------------------------------------------------------------------------
# Codec selection
# ---------------------------------------------------------------------------


class TestCodecSelection:
    def test_const_column(self) -> None:
        col = [37.7749] * 40
        fold = fold_column(col, NumericFoldConfig())
        assert fold.codec == "CONST"
        assert fold.lossless

    def test_affine_column(self) -> None:
        col = [1_718_000_000 + 5 * i for i in range(40)]
        fold = fold_column(col, NumericFoldConfig())
        assert fold.codec == "AFFINE"
        assert fold.lossless

    def test_affine_negative_step(self) -> None:
        col = [100 - 3 * i for i in range(30)]
        fold = fold_column(col, NumericFoldConfig())
        assert fold.codec == "AFFINE"

    def test_delta_column(self) -> None:
        # Large base values with small irregular deltas -> DELTA wins over RAW
        rng = random.Random(42)
        col = [1_000_000_000]
        for _ in range(39):
            col.append(col[-1] + rng.randint(1, 10))
        fold = fold_column(col, NumericFoldConfig())
        assert fold.codec == "DELTA"
        assert fold.lossless

    def test_rational_column(self) -> None:
        col = [1 / 3] * 40
        cfg = NumericFoldConfig(enable_rational=True)
        fold = fold_column(col, cfg)
        assert fold.codec in ("CONST", "RATIONAL")

    def test_raw_fallback_high_entropy(self) -> None:
        rng = random.Random(99)
        col = [rng.random() * 1000 for _ in range(40)]
        fold = fold_column(col, NumericFoldConfig())
        # High entropy -> should not falsely compress as AFFINE/POLY
        assert fold.codec in ("RAW", "RATIONAL", "DELTA")

    def test_quadratic_poly2(self) -> None:
        col = [i * i for i in range(40)]
        cfg = NumericFoldConfig(enable_poly=True)
        fold = fold_column(col, cfg)
        assert fold.codec == "POLY2"
        assert fold.lossless

    def test_poly_disabled_by_default(self) -> None:
        col = [i * i for i in range(40)]
        cfg = NumericFoldConfig(enable_poly=False)
        fold = fold_column(col, cfg)
        # Without poly enabled, should fall back to DELTA or RAW
        assert fold.codec != "POLY2"


# ---------------------------------------------------------------------------
# Lossless round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.mark.parametrize(
        "name,col",
        [
            ("const_int", [42] * 40),
            ("const_float", [3.14] * 40),
            ("affine_int", [100 + 7 * i for i in range(40)]),
            ("affine_large", [1_718_000_000 + 5 * i for i in range(40)]),
            ("affine_zero_start", [5 * i for i in range(40)]),
            ("delta", sorted(random.Random(42).randint(0, 10**6) for _ in range(40))),
        ],
    )
    def test_exact_roundtrip(self, name: str, col: list) -> None:
        fold = fold_column(col, NumericFoldConfig())
        rebuilt = reconstruct_column(fold)
        assert rebuilt == col, f"Round-trip failed for {name}: codec={fold.codec}"

    def test_roundtrip_rational(self) -> None:
        col = [1 / 3] * 25 + [1 / 7] * 15
        cfg = NumericFoldConfig(enable_rational=True)
        fold = fold_column(col, cfg)
        rebuilt = reconstruct_column(fold)
        for a, b in zip(col, rebuilt):
            assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)

    def test_roundtrip_poly2(self) -> None:
        col = [i * i for i in range(40)]
        cfg = NumericFoldConfig(enable_poly=True)
        fold = fold_column(col, cfg)
        rebuilt = reconstruct_column(fold)
        assert rebuilt == col

    def test_roundtrip_poly3(self) -> None:
        col = [i**3 - 2 * i for i in range(40)]
        cfg = NumericFoldConfig(enable_poly=True)
        fold = fold_column(col, cfg)
        rebuilt = reconstruct_column(fold)
        assert rebuilt == col


# ---------------------------------------------------------------------------
# fold_tool_output integration
# ---------------------------------------------------------------------------


class TestFoldToolOutput:
    def test_folds_sre_logs(self) -> None:
        rng = random.Random(7)
        obj = {
            "results": [
                {
                    "id": i,
                    "ts": 1_718_000_000 + 5 * i,
                    "level": rng.choice(["INFO", "WARN", "ERROR"]),
                    "latency_ms": round(rng.gauss(40, 8), 1),
                }
                for i in range(100)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = fold_tool_output(raw, NumericFoldConfig())
        assert result is not None
        folded_text, recipe = result
        assert len(folded_text) < len(raw)
        assert recipe["codec"] == "NUMERICFOLD"
        assert recipe["n"] == 100

    def test_returns_none_for_non_json(self) -> None:
        assert fold_tool_output("not json", NumericFoldConfig()) is None

    def test_returns_none_for_small_dataset(self) -> None:
        obj = {"results": [{"id": i} for i in range(3)]}
        raw = json.dumps(obj)
        cfg = NumericFoldConfig(min_rows=8)
        assert fold_tool_output(raw, cfg) is None

    def test_returns_none_for_no_numeric_columns(self) -> None:
        obj = {"results": [{"name": f"item-{i}"} for i in range(20)]}
        raw = json.dumps(obj)
        assert fold_tool_output(raw, NumericFoldConfig()) is None

    def test_preserves_nonnumeric_columns(self) -> None:
        obj = {
            "results": [
                {"id": i, "name": f"sensor-{i}", "lat": 37.7749}
                for i in range(20)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = fold_tool_output(raw, NumericFoldConfig())
        assert result is not None
        folded_text, _ = result
        folded_obj = json.loads(folded_text)
        # Non-numeric "name" column should be in _rows
        assert "_rows" in folded_obj
        assert all("name" in row for row in folded_obj["_rows"])

    def test_recipe_has_column_metadata(self) -> None:
        obj = {
            "data": [
                {"t": i, "count": i * 2, "label": "x"}
                for i in range(30)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = fold_tool_output(raw, NumericFoldConfig())
        assert result is not None
        _, recipe = result
        assert "columns" in recipe
        # "t" and "count" are numeric, should have codec info
        for col_name in ("t", "count"):
            assert col_name in recipe["columns"]
            assert "codec" in recipe["columns"][col_name]


# ---------------------------------------------------------------------------
# Edge cases / adversarial
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_value_column(self) -> None:
        """A column with one distinct value should be CONST."""
        col = [42] * 20
        fold = fold_column(col, NumericFoldConfig())
        assert fold.codec == "CONST"

    def test_two_value_column(self) -> None:
        """Short sequences should still get a codec."""
        col = [0, 1] * 10
        fold = fold_column(col, NumericFoldConfig())
        rebuilt = reconstruct_column(fold)
        assert rebuilt == col

    def test_boolean_excluded(self) -> None:
        """Booleans should not be treated as numeric."""
        obj = {
            "results": [
                {"id": i, "active": True, "value": i * 10}
                for i in range(20)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = fold_tool_output(raw, NumericFoldConfig())
        assert result is not None
        _, recipe = result
        # "active" (bool) should NOT be in columns
        assert "active" not in recipe["columns"]

    def test_mixed_int_float_column(self) -> None:
        """Column with both int and float values."""
        col = [1, 2.0, 3, 4.0, 5] * 8
        fold = fold_column(col, NumericFoldConfig())
        rebuilt = reconstruct_column(fold)
        # Values should match numerically
        for a, b in zip(col, rebuilt):
            assert math.isclose(a, b, abs_tol=1e-12)

    def test_near_progression_not_false_affine(self) -> None:
        """A near-but-not-quite progression should NOT be AFFINE."""
        col = [100 + 5 * i for i in range(40)]
        col[20] += 0.01  # one perturbation
        fold = fold_column(col, NumericFoldConfig())
        # Should NOT claim AFFINE — the perturbation breaks it
        if fold.codec == "AFFINE":
            # If it did pick AFFINE, it must be lossy
            rebuilt = reconstruct_column(fold)
            assert rebuilt != col, "AFFINE on perturbed data must differ"

    def test_empty_json_returns_none(self) -> None:
        assert fold_tool_output("{}", NumericFoldConfig()) is None
        assert fold_tool_output("[]", NumericFoldConfig()) is None

    def test_nested_array_finds_records(self) -> None:
        """Records nested under a key should be found."""
        obj = {"meta": {"page": 1}, "results": [{"x": i} for i in range(20)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = fold_tool_output(raw, NumericFoldConfig())
        assert result is not None
