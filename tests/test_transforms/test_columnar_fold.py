"""Tests for ColumnarFold transform."""

from __future__ import annotations

import json

import pytest

from headroom.transforms.columnar_fold import (
    ColumnarResult,
    columnar_fold,
    reconstruct_columnar,
)
from headroom.transforms.numeric_fold import NumericFoldConfig


class TestColumnarFold:
    def test_folds_sre_logs(self) -> None:
        obj = {
            "results": [
                {
                    "id": i,
                    "ts": 1_718_200_000 + 7 * i,
                    "level": ["INFO", "WARN", "ERROR"][i % 3],
                    "latency_ms": round(40 + i * 0.1, 1),
                    "msg": "request handled",
                }
                for i in range(50)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        assert len(result.folded_text) < len(raw)
        assert result.recipe["codec"] == "COLUMNARFOLD"
        assert result.recipe["n"] == 50

    def test_lossless_roundtrip(self) -> None:
        obj = {
            "results": [
                {
                    "id": i,
                    "ts": 1_718_200_000 + 5 * i,
                    "level": ["INFO", "WARN", "ERROR"][i % 3],
                    "latency_ms": round(40 + i * 0.1, 1),
                    "msg": "request handled",
                }
                for i in range(30)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        assert rebuilt == obj["results"]

    def test_returns_none_for_non_json(self) -> None:
        assert columnar_fold("not json") is None

    def test_returns_none_for_small_dataset(self) -> None:
        obj = {"results": [{"id": i} for i in range(3)]}
        assert columnar_fold(json.dumps(obj)) is None

    def test_preserves_column_types(self) -> None:
        obj = {
            "data": [
                {"name": f"item-{i}", "count": i * 10, "active": True}
                for i in range(20)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        for orig, rec in zip(obj["data"], rebuilt):
            assert orig["name"] == rec["name"]
            assert orig["active"] == rec["active"]

    def test_csv_dedup_saves_tokens(self) -> None:
        """CSV format should save chars vs repeated-key JSON."""
        obj = {
            "results": [
                {"id": i, "lat": 37.7749, "lng": -122.4194, "name": f"s-{i}"}
                for i in range(50)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        assert result.chars_after < result.chars_before

    def test_per_column_codecs(self) -> None:
        obj = {
            "data": [
                {"t": i, "count": i * 2, "label": "x"}
                for i in range(30)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        # t and count should be closed-form, label should be csv or dict
        assert result.per_column["t"] in ("AFFINE", "CONST")
        assert result.per_column["count"] in ("AFFINE", "CONST")
        assert result.per_column["label"].startswith(("csv:", "dict:"))

    def test_dict_encoding_low_cardinality(self) -> None:
        """Low-cardinality string columns should be dictionary-encoded."""
        obj = {
            "results": [
                {
                    "id": i,
                    "level": ["INFO", "WARN", "ERROR"][i % 3],
                    "msg": ["ok", "fail"][i % 2],
                }
                for i in range(60)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        # level (3 unique/60) and msg (2 unique/60) should be dict-encoded
        assert result.per_column["level"].startswith("dict:")
        assert result.per_column["msg"].startswith("dict:")
        # Verify lossless round-trip
        rebuilt = reconstruct_columnar(result.folded_text, result.recipe)
        assert rebuilt == obj["results"]
        # Dict encoding should produce @dict: lines in output
        assert "@dict:" in result.folded_text

    def test_dict_encoding_saves_tokens(self) -> None:
        """Dictionary encoding should save more than plain CSV on repeated strings."""
        obj = {
            "results": [
                {
                    "id": i,
                    "status": ["active", "inactive", "pending"][i % 3],
                    "region": ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"][i % 4],
                }
                for i in range(100)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))
        result = columnar_fold(raw)
        assert result is not None
        # Should save significantly more than just key dedup
        assert result.chars_after < result.chars_before * 0.5

    def test_transform_applies_to_tool_message(self) -> None:
        """ColumnarFoldTransform should compress tool message content."""
        import tiktoken
        from headroom.transforms.columnar_fold import ColumnarFoldTransform
        from headroom.transforms.numeric_fold import NumericFoldConfig
        from headroom.providers.anthropic import AnthropicProvider

        obj = {
            "results": [
                {"id": i, "ts": 1718200000 + 5 * i, "level": "INFO", "msg": "ok"}
                for i in range(50)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))

        provider = AnthropicProvider(warn=False)
        from headroom.tokenizer import Tokenizer
        tokenizer = Tokenizer(provider.get_token_counter("claude-sonnet-4-20250514"))

        messages = [
            {"role": "user", "content": "process"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "c1", "name": "t", "input": {}}
            ]},
            {"role": "tool", "tool_use_id": "c1", "content": raw},
        ]

        transform = ColumnarFoldTransform(NumericFoldConfig())
        result = transform.apply(messages, tokenizer)

        assert result.tokens_after < result.tokens_before
        assert any("columnar_fold" in t for t in result.transforms_applied)

    def test_beats_numeric_fold_on_mixed_data(self) -> None:
        """ColumnarFold should save more than NumericFold alone on
        data with both numeric and non-numeric columns."""
        from headroom.transforms.numeric_fold import fold_tool_output

        obj = {
            "results": [
                {
                    "id": i,
                    "ts": 1_718_200_000 + 7 * i,
                    "level": ["INFO", "WARN", "ERROR"][i % 3],
                    "msg": "request handled",
                }
                for i in range(100)
            ]
        }
        raw = json.dumps(obj, separators=(",", ":"))

        nf_result = fold_tool_output(raw, NumericFoldConfig())
        cf_result = columnar_fold(raw)

        assert nf_result is not None
        assert cf_result is not None

        nf_chars = len(nf_result[0])
        cf_chars = cf_result.chars_after
        # ColumnarFold should be smaller (CSV dedup of keys)
        assert cf_chars < nf_chars, (
            f"ColumnarFold ({cf_chars}) should beat NumericFold ({nf_chars})"
        )
