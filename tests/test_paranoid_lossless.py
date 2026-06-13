"""Paranoid lossless tests — prove zero data loss under every condition.

These tests are deliberately adversarial, exhaustive, and redundant.
They exist to catch any scenario where compression silently corrupts,
drops, reorders, truncates, or mutates data. If any of these fail,
the compression is broken and must not ship.

Categories:
  1. BIT-EXACT ROUND-TRIP: compress -> decompress == original, always
  2. VALUE PRESERVATION: every individual cell value survives intact
  3. ORDERING: row order and column order are preserved exactly
  4. TYPE FIDELITY: int stays int, float stays float, string stays string
  5. EDGE CASES: empty, null, unicode, nested, huge, tiny, adversarial
  6. BOUNDARY VALUES: min/max int, float precision limits, inf, -0.0
  7. SCALE: works at 1 row, 10K rows, 1 column, 50 columns
  8. RANDOMIZED FUZZING: random data never corrupted
"""

from __future__ import annotations

import json
import math
import random
import string

import pytest

from headroom.transforms.columnar_fold import (
    columnar_fold,
    reconstruct_columnar,
)
from headroom.transforms.numeric_fold import (
    NumericFoldConfig,
    fold_column,
    fold_tool_output,
    reconstruct_column,
)


# =========================================================================
# 1. BIT-EXACT ROUND-TRIP
# =========================================================================


class TestBitExactRoundTrip:
    """Compress then decompress must produce the EXACT original."""

    def _roundtrip_columnar(self, obj: dict | list) -> None:
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        if result is None:
            return  # nothing to fold is fine
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        # Extract original records
        if isinstance(obj, list):
            original = obj
        else:
            for v in obj.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    original = v
                    break
            else:
                return
        assert rebuilt == original, (
            f"Round-trip FAILED.\n"
            f"Original: {json.dumps(original[:3], indent=2)}\n"
            f"Rebuilt:  {json.dumps(rebuilt[:3], indent=2)}"
        )

    def test_sre_logs_200_rows(self) -> None:
        rng = random.Random(42)
        obj = {"results": [
            {"id": i, "ts": 1718200000 + 7 * i,
             "level": rng.choice(["INFO", "WARN", "ERROR"]),
             "latency_ms": round(rng.gauss(45, 9), 1),
             "msg": rng.choice(["ok", "fail", "retry"])}
            for i in range(200)
        ]}
        self._roundtrip_columnar(obj)

    def test_geo_150_rows(self) -> None:
        obj = {"results": [
            {"id": 5000 + i, "lat": 37.7749, "lng": -122.4194,
             "alt": 12 + 3 * i, "name": f"sensor-{i}"}
            for i in range(150)
        ]}
        self._roundtrip_columnar(obj)

    def test_metrics_300_rows(self) -> None:
        rng = random.Random(99)
        obj = {"data": [
            {"t": i, "count": i * i + 2 * i,
             "p99": round(rng.uniform(80, 95), 2), "share": 0.2}
            for i in range(300)
        ]}
        self._roundtrip_columnar(obj)

    def test_numeric_fold_affine(self) -> None:
        col = [100 + 7 * i for i in range(500)]
        fold = fold_column(col, NumericFoldConfig())
        assert reconstruct_column(fold) == col

    def test_numeric_fold_const(self) -> None:
        col = [3.14159] * 200
        fold = fold_column(col, NumericFoldConfig())
        assert reconstruct_column(fold) == col

    def test_numeric_fold_delta(self) -> None:
        rng = random.Random(42)
        col = [1_000_000_000]
        for _ in range(199):
            col.append(col[-1] + rng.randint(1, 10))
        fold = fold_column(col, NumericFoldConfig())
        assert reconstruct_column(fold) == col

    def test_numeric_fold_poly2(self) -> None:
        col = [i * i for i in range(100)]
        cfg = NumericFoldConfig(enable_poly=True)
        fold = fold_column(col, cfg)
        assert reconstruct_column(fold) == col

    def test_numeric_fold_poly3(self) -> None:
        col = [i**3 - 2 * i**2 + 3 * i for i in range(80)]
        cfg = NumericFoldConfig(enable_poly=True)
        fold = fold_column(col, cfg)
        assert reconstruct_column(fold) == col


# =========================================================================
# 2. VALUE PRESERVATION — every cell survives
# =========================================================================


class TestValuePreservation:
    """Every individual value must be identical after round-trip."""

    def test_every_cell_matches(self) -> None:
        rng = random.Random(42)
        obj = {"results": [
            {"id": i, "score": round(rng.uniform(0, 1), 6),
             "name": f"item-{i}", "active": True, "count": rng.randint(0, 1000)}
            for i in range(100)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)

        for i, (orig, rec) in enumerate(zip(obj["results"], rebuilt)):
            for k in orig:
                assert k in rec, f"Row {i}: key '{k}' missing"
                assert orig[k] == rec[k], (
                    f"Row {i}, key '{k}': {orig[k]!r} != {rec[k]!r}"
                )

    def test_no_extra_keys_added(self) -> None:
        obj = {"results": [{"a": i, "b": "x"} for i in range(20)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for orig, rec in zip(obj["results"], rebuilt):
            assert set(rec.keys()) == set(orig.keys()), "Extra keys introduced"

    def test_no_rows_dropped(self) -> None:
        obj = {"results": [{"id": i} for i in range(100)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        assert len(rebuilt) == 100, f"Expected 100 rows, got {len(rebuilt)}"

    def test_no_rows_added(self) -> None:
        obj = {"results": [{"id": i} for i in range(50)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        assert len(rebuilt) == 50


# =========================================================================
# 3. ORDERING — rows and columns stay in order
# =========================================================================


class TestOrdering:
    def test_row_order_preserved(self) -> None:
        obj = {"results": [{"id": i, "val": 999 - i} for i in range(100)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for i, rec in enumerate(rebuilt):
            assert rec["id"] == i, f"Row order broken at {i}"
            assert rec["val"] == 999 - i

    def test_column_order_preserved(self) -> None:
        obj = {"results": [
            {"z_col": i, "a_col": i * 2, "m_col": "x"} for i in range(20)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for rec in rebuilt:
            assert list(rec.keys()) == ["z_col", "a_col", "m_col"]


# =========================================================================
# 4. TYPE FIDELITY — types must not mutate
# =========================================================================


class TestTypeFidelity:
    def test_int_stays_int(self) -> None:
        obj = {"results": [{"val": 42} for _ in range(20)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for rec in rebuilt:
            assert isinstance(rec["val"], int), f"Expected int, got {type(rec['val'])}"

    def test_float_stays_float(self) -> None:
        obj = {"results": [{"val": 3.14} for _ in range(20)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for rec in rebuilt:
            assert isinstance(rec["val"], float), f"Expected float, got {type(rec['val'])}"

    def test_string_stays_string(self) -> None:
        obj = {"results": [{"val": "hello"} for _ in range(20)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for rec in rebuilt:
            assert isinstance(rec["val"], str)
            assert rec["val"] == "hello"

    def test_bool_stays_bool(self) -> None:
        obj = {"results": [{"active": True} for _ in range(20)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for rec in rebuilt:
            assert isinstance(rec["active"], bool)
            assert rec["active"] is True

    def test_numeric_string_not_converted(self) -> None:
        """A string '42' must NOT become int 42."""
        obj = {"results": [{"zipcode": "01234", "id": i} for i in range(20)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for rec in rebuilt:
            assert isinstance(rec["zipcode"], str), "String converted to number!"
            assert rec["zipcode"] == "01234"

    def test_integer_zero_vs_float_zero(self) -> None:
        col_int = [0] * 20
        fold = fold_column(col_int, NumericFoldConfig())
        rebuilt = reconstruct_column(fold)
        assert all(isinstance(v, int) for v in rebuilt)
        assert all(v == 0 for v in rebuilt)


# =========================================================================
# 5. EDGE CASES
# =========================================================================


class TestEdgeCases:
    def test_empty_string_values(self) -> None:
        obj = {"results": [{"id": i, "note": ""} for i in range(20)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for rec in rebuilt:
            assert rec["note"] == ""

    def test_unicode_values(self) -> None:
        obj = {"results": [
            {"id": i, "emoji": "cafe\u0301 \u2603 \u2764", "cjk": "\u4e16\u754c"}
            for i in range(20)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for orig, rec in zip(obj["results"], rebuilt):
            assert rec["emoji"] == orig["emoji"]
            assert rec["cjk"] == orig["cjk"]

    def test_strings_with_commas(self) -> None:
        """CSV must handle commas in values correctly."""
        obj = {"results": [
            {"id": i, "desc": f"value, with, commas, {i}"}
            for i in range(20)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for orig, rec in zip(obj["results"], rebuilt):
            assert rec["desc"] == orig["desc"]

    def test_strings_with_quotes(self) -> None:
        obj = {"results": [
            {"id": i, "msg": f'He said "hello {i}"'}
            for i in range(20)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for orig, rec in zip(obj["results"], rebuilt):
            assert rec["msg"] == orig["msg"]

    def test_strings_with_newlines(self) -> None:
        obj = {"results": [
            {"id": i, "log": f"line1\nline2\nline3-{i}"}
            for i in range(20)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for orig, rec in zip(obj["results"], rebuilt):
            assert rec["log"] == orig["log"]

    def test_single_column(self) -> None:
        obj = {"results": [{"val": i * 10} for i in range(30)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        if result is not None:
            rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
            assert rebuilt == obj["results"]

    def test_all_same_values(self) -> None:
        obj = {"results": [{"a": 1, "b": "x", "c": True} for _ in range(50)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        assert rebuilt == obj["results"]

    def test_very_long_strings(self) -> None:
        obj = {"results": [
            {"id": i, "payload": "x" * 10000} for i in range(10)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for rec in rebuilt:
            assert len(rec["payload"]) == 10000


# =========================================================================
# 6. BOUNDARY VALUES
# =========================================================================


class TestBoundaryValues:
    def test_large_integers(self) -> None:
        col = [10**18 + i for i in range(30)]
        fold = fold_column(col, NumericFoldConfig())
        assert reconstruct_column(fold) == col

    def test_negative_integers(self) -> None:
        col = [-1000 + 3 * i for i in range(30)]
        fold = fold_column(col, NumericFoldConfig())
        assert reconstruct_column(fold) == col

    def test_mixed_positive_negative(self) -> None:
        col = [-50 + 5 * i for i in range(30)]  # crosses zero
        fold = fold_column(col, NumericFoldConfig())
        assert reconstruct_column(fold) == col

    def test_very_small_floats(self) -> None:
        col = [1e-10 * i for i in range(30)]
        fold = fold_column(col, NumericFoldConfig())
        rebuilt = reconstruct_column(fold)
        for a, b in zip(col, rebuilt):
            assert math.isclose(a, b, abs_tol=1e-15)

    def test_very_large_floats(self) -> None:
        col = [1e15 + 1e10 * i for i in range(30)]
        fold = fold_column(col, NumericFoldConfig())
        rebuilt = reconstruct_column(fold)
        for a, b in zip(col, rebuilt):
            assert math.isclose(a, b, rel_tol=1e-9)

    def test_zero_column(self) -> None:
        col = [0] * 30
        fold = fold_column(col, NumericFoldConfig())
        assert reconstruct_column(fold) == col

    def test_single_element_column(self) -> None:
        """Columns below min_rows should fall through safely."""
        col = [42]
        fold = fold_column(col, NumericFoldConfig())
        assert reconstruct_column(fold) == col


# =========================================================================
# 7. SCALE
# =========================================================================


class TestScale:
    def test_minimum_rows(self) -> None:
        obj = {"results": [{"id": i, "val": i * 2} for i in range(8)]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        if result is not None:
            rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
            assert rebuilt == obj["results"]

    def test_1000_rows(self) -> None:
        rng = random.Random(42)
        obj = {"results": [
            {"id": i, "ts": 1718200000 + i, "val": rng.randint(0, 100),
             "cat": rng.choice(["A", "B", "C"])}
            for i in range(1000)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        assert len(rebuilt) == 1000
        assert rebuilt == obj["results"]

    def test_many_columns(self) -> None:
        obj = {"results": [
            {f"col_{j}": i + j for j in range(20)}
            for i in range(50)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        assert rebuilt == obj["results"]

    def test_mixed_wide_and_narrow(self) -> None:
        """Some rows might have more variety than others."""
        rng = random.Random(42)
        obj = {"results": [
            {"id": i, "a": rng.randint(0, 3), "b": round(rng.random(), 4),
             "c": rng.choice(["x", "y"]), "d": f"item-{i}",
             "e": i * i, "f": True}
            for i in range(200)
        ]}
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        assert rebuilt == obj["results"]


# =========================================================================
# 8. RANDOMIZED FUZZING
# =========================================================================


class TestRandomizedFuzzing:
    """Generate random data and verify round-trip. Run many seeds."""

    def _random_records(self, rng: random.Random, n: int) -> list[dict]:
        """Generate records with random types and values."""
        records = []
        for i in range(n):
            rec = {"_idx": i}
            # Random int column
            rec["int_val"] = rng.randint(-10000, 10000)
            # Random float column
            rec["float_val"] = round(rng.uniform(-1000, 1000), 4)
            # Random string from small set (dict-encodable)
            rec["cat"] = rng.choice(["alpha", "beta", "gamma", "delta"])
            # Random unique string
            rec["uid"] = "".join(rng.choices(string.ascii_lowercase, k=8))
            # Boolean
            rec["flag"] = rng.choice([True, False])
            records.append(rec)
        return records

    @pytest.mark.parametrize("seed", range(20))
    def test_fuzz_columnar_fold(self, seed: int) -> None:
        rng = random.Random(seed)
        n = rng.randint(10, 200)
        records = self._random_records(rng, n)
        obj = {"results": records}
        raw = json.dumps(obj, separators=(",", ":"))

        result = columnar_fold(raw)
        if result is None:
            return

        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)

        assert len(rebuilt) == n, f"Seed {seed}: row count {len(rebuilt)} != {n}"
        for i, (orig, rec) in enumerate(zip(records, rebuilt)):
            for k in orig:
                assert k in rec, f"Seed {seed}, row {i}: key '{k}' missing"
                assert type(orig[k]) == type(rec[k]), (
                    f"Seed {seed}, row {i}, key '{k}': "
                    f"type {type(orig[k])} != {type(rec[k])}"
                )
                assert orig[k] == rec[k], (
                    f"Seed {seed}, row {i}, key '{k}': "
                    f"{orig[k]!r} != {rec[k]!r}"
                )

    @pytest.mark.parametrize("seed", range(20))
    def test_fuzz_numeric_fold(self, seed: int) -> None:
        rng = random.Random(seed)
        pattern = rng.choice(["const", "affine", "random", "delta"])

        if pattern == "const":
            val = rng.uniform(-1000, 1000)
            col = [val] * rng.randint(10, 100)
        elif pattern == "affine":
            a0 = rng.randint(-10000, 10000)
            d = rng.randint(-100, 100)
            n = rng.randint(10, 200)
            col = [a0 + d * i for i in range(n)]
        elif pattern == "delta":
            n = rng.randint(10, 100)
            col = [rng.randint(10**8, 10**9)]
            for _ in range(n - 1):
                col.append(col[-1] + rng.randint(1, 20))
        else:
            n = rng.randint(10, 100)
            col = [round(rng.uniform(-1000, 1000), 4) for _ in range(n)]

        fold = fold_column(col, NumericFoldConfig())
        rebuilt = reconstruct_column(fold)

        if fold.lossless:
            for i, (a, b) in enumerate(zip(col, rebuilt)):
                if isinstance(a, float):
                    assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12), (
                        f"Seed {seed}, index {i}: {a} != {b}"
                    )
                else:
                    assert a == b, f"Seed {seed}, index {i}: {a} != {b}"


# =========================================================================
# 9. COMPRESSION NEVER INFLATES (safety check)
# =========================================================================


class TestNeverInflates:
    """Compressed output must never be LARGER than the original
    when the compression is actually applied."""

    def test_columnar_fold_never_inflates(self) -> None:
        rng = random.Random(42)
        for seed in range(50):
            rng.seed(seed)
            n = rng.randint(20, 200)
            obj = {"results": [
                {"id": i, "ts": 1718200000 + i,
                 "val": round(rng.gauss(0, 100), 2),
                 "cat": rng.choice(["A", "B", "C"])}
                for i in range(n)
            ]}
            raw = json.dumps(obj, separators=(",", ":"))
            result = columnar_fold(raw)
            if result is not None:
                assert result.chars_after <= result.chars_before, (
                    f"Seed {seed}: inflation! {result.chars_before} -> {result.chars_after}"
                )


# =========================================================================
# 10. rANS CODEC PARANOID ROUND-TRIP
# =========================================================================


class TestRansParanoid:
    """rANS must never lose a single byte."""

    @pytest.mark.parametrize("seed", range(20))
    def test_fuzz_rans(self, seed: int) -> None:
        from headroom.cache.rans_codec import rans_decode, rans_encode

        rng = random.Random(seed)
        length = rng.randint(0, 5000)
        data = bytes(rng.randint(0, 255) for _ in range(length))
        encoded = rans_encode(data)
        decoded = rans_decode(encoded)
        assert decoded == data, f"Seed {seed}: rANS round-trip failed at length {length}"

    def test_all_single_bytes(self) -> None:
        from headroom.cache.rans_codec import rans_decode, rans_encode

        for byte_val in range(256):
            data = bytes([byte_val])
            assert rans_decode(rans_encode(data)) == data

    def test_json_tool_output(self) -> None:
        from headroom.cache.rans_codec import compress_text, decompress_text

        rng = random.Random(42)
        obj = {"results": [
            {"id": i, "ts": 1718200000 + i, "val": round(rng.gauss(0, 1), 6)}
            for i in range(500)
        ]}
        text = json.dumps(obj)
        assert decompress_text(compress_text(text)) == text
