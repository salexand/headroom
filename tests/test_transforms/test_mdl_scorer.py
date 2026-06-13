"""Tests for MDL-based compressor scoring."""

from __future__ import annotations

from headroom.transforms.mdl_scorer import (
    MDLCandidate,
    MDLResult,
    estimate_model_cost,
    mdl_score,
    mdl_select,
)


def _fake_token_count(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


class TestMDLScore:
    def test_score_identity(self) -> None:
        result = mdl_score(
            "hello world",
            "raw",
            compress_fn=lambda x: x,
            token_count_fn=_fake_token_count,
            model_cost=0,
        )
        assert result.name == "raw"
        assert result.model_cost == 0
        assert result.data_cost == _fake_token_count("hello world")
        assert result.total_cost == result.data_cost
        assert result.error is None

    def test_score_compressor_that_saves(self) -> None:
        result = mdl_score(
            "a" * 1000,
            "test_compressor",
            compress_fn=lambda x: "compressed(1000 a's)",
            token_count_fn=_fake_token_count,
            model_cost=5,
        )
        assert result.data_cost < _fake_token_count("a" * 1000)
        assert result.total_cost == result.model_cost + result.data_cost

    def test_score_compressor_that_fails(self) -> None:
        def bad_compress(x: str) -> str:
            raise ValueError("broken")

        result = mdl_score(
            "hello",
            "broken",
            compress_fn=bad_compress,
            token_count_fn=_fake_token_count,
        )
        assert result.error is not None
        assert "ValueError" in result.error
        # Failed compressor returns original content
        assert result.compressed == "hello"


class TestMDLSelect:
    def test_selects_best_compressor(self) -> None:
        content = "a" * 1000

        result = mdl_select(
            content,
            candidates=[
                ("good", lambda x: "short"),  # very compressed
                ("bad", lambda x: x + x),  # inflates
            ],
            token_count_fn=_fake_token_count,
        )
        assert result.best.name == "good"
        assert len(result.candidates) == 3  # raw + good + bad

    def test_selects_raw_when_all_inflate(self) -> None:
        content = "tiny"

        result = mdl_select(
            content,
            candidates=[
                ("inflater", lambda x: x * 100),
            ],
            token_count_fn=_fake_token_count,
        )
        # raw should win because inflater makes it worse
        assert result.best.name == "raw"

    def test_always_includes_raw_baseline(self) -> None:
        result = mdl_select(
            "test",
            candidates=[("a", lambda x: x)],
            token_count_fn=_fake_token_count,
        )
        names = {c.name for c in result.candidates}
        assert "raw" in names

    def test_model_cost_can_tip_selection(self) -> None:
        """A compressor with high model cost should lose to raw even
        if it compresses slightly."""
        content = "hello world test"  # 4 tokens

        result = mdl_select(
            content,
            candidates=[
                # Compresses to 3 tokens but has 5 token model cost = 8 total
                ("expensive", lambda x: "hi"),
            ],
            token_count_fn=_fake_token_count,
            model_costs={"expensive": 5},
        )
        # raw = 0 + 4 = 4, expensive = 5 + 1 = 6 -> raw wins
        assert result.best.name == "raw"

    def test_original_tokens_recorded(self) -> None:
        result = mdl_select(
            "test data",
            candidates=[],
            token_count_fn=_fake_token_count,
        )
        assert result.original_tokens == _fake_token_count("test data")


class TestModelCosts:
    def test_known_compressors_have_costs(self) -> None:
        for name in ("raw", "smart_crusher", "numeric_fold", "columnar_fold"):
            cost = estimate_model_cost(name)
            assert isinstance(cost, int)
            assert cost >= 0

    def test_unknown_compressor_gets_default(self) -> None:
        cost = estimate_model_cost("unknown_compressor_xyz")
        assert cost == 10  # default
