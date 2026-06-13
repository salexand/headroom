"""Tests for headroom.bench harness skeleton."""

from __future__ import annotations

import csv
import io
import json

import pytest

from headroom.bench._types import BenchResult, CompressedOutput, Dataset, SuiteConfig
from headroom.bench.loader import (
    SUITES,
    load_builtin,
    load_file,
    load_suite,
)
from headroom.bench.adapters import (
    GzipAdapter,
    HeadroomUpstreamAdapter,
    LeanCtxAdapter,
    NumericFoldAdapter,
    RTKAdapter,
    RawAdapter,
    UnavailableAdapter,
    _leanctx_available,
    _rtk_available,
    get_adapters,
)
from headroom.bench.scorer import score
from headroom.bench.reporter import (
    write_coverage_heatmap,
    write_csv,
    write_fairness_header,
    write_markdown,
)


# ---- loader ---------------------------------------------------------------


class TestLoader:
    def test_load_builtin_sre_logs(self) -> None:
        ds = load_builtin("sre_logs")
        assert ds.name == "sre_logs"
        assert ds.category == "numeric"
        assert len(ds.records) == 200
        assert ds.checksum  # non-empty hash

    def test_load_builtin_geo(self) -> None:
        ds = load_builtin("geo_search")
        assert ds.category == "numeric"
        assert len(ds.records) == 150

    def test_load_builtin_metrics(self) -> None:
        ds = load_builtin("metrics_timeseries")
        assert len(ds.records) == 300

    def test_load_builtin_adversarial(self) -> None:
        ds = load_builtin("adversarial_floats")
        assert ds.category == "adversarial"
        assert len(ds.records) == 60

    # -- agent workloads --

    def test_load_builtin_code_search(self) -> None:
        ds = load_builtin("code_search")
        assert ds.category == "agent"
        assert len(ds.records) == 80
        assert "file" in ds.records[0]

    def test_load_builtin_github_issues(self) -> None:
        ds = load_builtin("github_issues")
        assert ds.category == "agent"
        assert len(ds.records) == 100

    def test_load_builtin_codebase_exploration(self) -> None:
        ds = load_builtin("codebase_exploration")
        assert ds.category == "agent"
        assert len(ds.records) == 120

    # -- numeric-heavy --

    def test_load_builtin_api_response(self) -> None:
        ds = load_builtin("api_response")
        assert ds.category == "numeric-heavy"
        assert len(ds.records) == 200
        # Should have dense numeric columns
        assert "p50_ms" in ds.records[0]

    def test_load_builtin_embeddings(self) -> None:
        ds = load_builtin("embeddings")
        assert ds.category == "numeric-heavy"
        assert len(ds.records) == 100
        assert "embedding" in ds.records[0]

    def test_load_builtin_timeseries(self) -> None:
        ds = load_builtin("timeseries")
        assert ds.category == "numeric-heavy"
        assert len(ds.records) == 250

    # -- adversarial (expanded) --

    def test_load_builtin_near_progression(self) -> None:
        ds = load_builtin("near_progression")
        assert ds.category == "adversarial"
        assert len(ds.records) == 80

    def test_load_builtin_mixed_types(self) -> None:
        ds = load_builtin("mixed_types")
        assert ds.category == "adversarial"
        assert len(ds.records) == 60
        # Some rows have "N/A" for value, others have int
        has_str = any(isinstance(r["value"], str) for r in ds.records)
        has_int = any(isinstance(r["value"], int) for r in ds.records)
        assert has_str and has_int

    def test_load_suite_agent(self) -> None:
        datasets = load_suite("agent")
        names = {d.name for d in datasets}
        assert names == {"code_search", "github_issues", "codebase_exploration"}

    def test_load_suite_numeric_heavy(self) -> None:
        datasets = load_suite("numeric-heavy")
        names = {d.name for d in datasets}
        assert names == {"api_response", "embeddings", "timeseries"}

    def test_load_builtin_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown dataset"):
            load_builtin("nonexistent")

    def test_load_suite_all(self) -> None:
        datasets = load_suite("all")
        assert len(datasets) == len(SUITES["all"])
        names = {d.name for d in datasets}
        assert names == set(SUITES["all"])

    def test_load_suite_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown suite"):
            load_suite("nonexistent")

    def test_load_file(self, tmp_path: pytest.TempPathFactory) -> None:
        data = {"results": [{"id": i, "val": i * 2} for i in range(10)]}
        p = tmp_path / "test_data.json"
        p.write_text(json.dumps(data))
        ds = load_file(p)
        assert ds.name == "test_data"
        assert ds.category == "custom"
        assert len(ds.records) == 10

    def test_datasets_are_deterministic(self) -> None:
        """Same seed -> same checksum."""
        a = load_builtin("sre_logs")
        b = load_builtin("sre_logs")
        assert a.checksum == b.checksum
        assert a.raw_json == b.raw_json


# ---- adapters --------------------------------------------------------------


class TestAdapters:
    def test_raw_adapter_identity(self) -> None:
        adapter = RawAdapter()
        out = adapter.compress("hello world")
        assert out.text == "hello world"
        assert out.chars_before == out.chars_after
        assert out.reversible is True
        assert out.error is None

    def test_gzip_adapter_compresses_bytes(self) -> None:
        adapter = GzipAdapter()
        context = "a" * 10_000
        out = adapter.compress(context)
        assert out.adapter_name == "gzip"
        # gzip should compress repeated chars well (bytes, not tokens)
        assert out.chars_after < out.chars_before
        # text is unchanged (gzip is storage-only)
        assert out.text == context
        assert out.latency_ms >= 0

    def test_unavailable_adapter_returns_error(self) -> None:
        adapter = UnavailableAdapter("rtk")
        out = adapter.compress("test")
        assert out.error == "adapter not available"
        assert out.text == "test"

    def test_numeric_fold_adapter_compresses(self) -> None:
        ds = load_builtin("sre_logs")
        adapter = NumericFoldAdapter()
        out = adapter.compress(ds.raw_json)
        assert out.adapter_name == "numeric-fold"
        assert out.error is None
        # SRE logs have numeric columns -> should compress
        assert out.chars_after < out.chars_before
        assert out.reversible is True

    def test_numeric_fold_adapter_no_numeric_data(self) -> None:
        adapter = NumericFoldAdapter()
        context = '{"items":[{"name":"a"},{"name":"b"}]}'
        out = adapter.compress(context)
        # No numeric columns -> unchanged
        assert out.text == context
        assert out.error is None

    def test_rtk_adapter_compresses_json(self) -> None:
        if not _rtk_available():
            pytest.skip("rtk binary not installed")
        adapter = RTKAdapter()
        ds = load_builtin("sre_logs")
        out = adapter.compress(ds.raw_json)
        assert out.adapter_name == "rtk"
        assert out.error is None
        # RTK truncates JSON arrays -> smaller output
        assert out.chars_after < out.chars_before
        assert out.reversible is False

    def test_rtk_adapter_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "headroom.bench.adapters._rtk_available", lambda: False
        )
        adapter = RTKAdapter()
        out = adapter.compress('{"a":1}')
        assert out.error is not None
        assert "not found" in out.error

    def test_leanctx_adapter_runs(self) -> None:
        if not _leanctx_available():
            pytest.skip("leanctx not installed")
        adapter = LeanCtxAdapter()
        ds = load_builtin("sre_logs")
        out = adapter.compress(ds.raw_json)
        assert out.adapter_name == "lean-ctx"
        assert out.error is None
        # leanctx Verbatim mode may not compress, but should not error
        assert out.text is not None

    def test_leanctx_adapter_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "headroom.bench.adapters._leanctx_available", lambda: False
        )
        adapter = LeanCtxAdapter()
        out = adapter.compress('{"a":1}')
        assert out.error is not None
        assert "not installed" in out.error

    def test_upstream_adapter_protocol(self) -> None:
        adapter = HeadroomUpstreamAdapter()
        assert adapter.name == "headroom-upstream"
        # Just verify it returns a CompressedOutput (may error without deps)
        out = adapter.compress('{"results":[{"id":1}]}')
        assert isinstance(out, CompressedOutput)

    def test_get_adapters_default(self) -> None:
        adapters = get_adapters()
        names = [a.name for a in adapters]
        assert "raw" in names
        assert "gzip" in names
        assert "numeric-fold" in names
        # headroom pipeline adapter is opt-in (slow)
        assert "headroom" not in names

    def test_get_adapters_with_pipeline(self) -> None:
        adapters = get_adapters(include_pipeline=True)
        names = [a.name for a in adapters]
        assert "headroom" in names

    def test_get_adapters_with_competitors(self) -> None:
        adapters = get_adapters(include_competitors=True)
        names = [a.name for a in adapters]
        # Competitors always show up (real or stub depending on install)
        assert "rtk" in names
        assert "lean-ctx" in names

    def test_get_adapters_with_unavailable(self) -> None:
        adapters = get_adapters(include_unavailable=True)
        names = [a.name for a in adapters]
        assert "rtk" in names
        assert "lean-ctx" in names
        assert "headroom-upstream" in names
        assert "headroom" in names


# ---- scorer ----------------------------------------------------------------


class TestScorer:
    def test_score_raw_adapter(self) -> None:
        ds = load_builtin("sre_logs")
        raw = RawAdapter()
        out = raw.compress(ds.raw_json)
        result = score(ds, out, tokenizer_name="cl100k_base")
        assert result.adapter == "raw"
        assert result.tokens_saved_pct == 0.0
        assert result.tokens_before == result.tokens_after
        assert result.tokens_before > 0

    def test_score_gzip_no_token_savings(self) -> None:
        ds = load_builtin("sre_logs")
        gz = GzipAdapter()
        out = gz.compress(ds.raw_json)
        result = score(ds, out, tokenizer_name="cl100k_base")
        # gzip doesn't change text -> no token savings
        assert result.tokens_saved_pct == 0.0

    def test_score_with_error(self) -> None:
        ds = load_builtin("sre_logs")
        out = CompressedOutput(
            adapter_name="broken",
            text=ds.raw_json,
            chars_before=len(ds.raw_json),
            chars_after=len(ds.raw_json),
            error="something went wrong",
        )
        result = score(ds, out)
        assert result.error == "something went wrong"


# ---- reporter --------------------------------------------------------------


class TestReporter:
    @pytest.fixture()
    def sample_results(self) -> list[BenchResult]:
        return [
            BenchResult(
                adapter="raw",
                dataset="sre_logs",
                category="numeric",
                tokenizer_name="cl100k_base",
                tokens_before=5000,
                tokens_after=5000,
                tokens_saved_pct=0.0,
                chars_before=20000,
                chars_after=20000,
                latency_ms=0.0,
                reversible=True,
            ),
            BenchResult(
                adapter="headroom",
                dataset="sre_logs",
                category="numeric",
                tokenizer_name="cl100k_base",
                tokens_before=5000,
                tokens_after=1500,
                tokens_saved_pct=70.0,
                chars_before=20000,
                chars_after=6000,
                latency_ms=3.5,
                reversible=True,
            ),
        ]

    def test_write_csv_structure(self, sample_results: list[BenchResult]) -> None:
        text = write_csv(sample_results)
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["adapter"] == "raw"
        assert rows[1]["adapter"] == "headroom"
        assert rows[1]["saved_pct"] == "70.0"

    def test_write_csv_to_file(
        self, sample_results: list[BenchResult], tmp_path: pytest.TempPathFactory
    ) -> None:
        p = tmp_path / "out.csv"
        with open(p, "w", newline="") as f:
            write_csv(sample_results, f)
        content = p.read_text()
        assert "raw" in content
        assert "headroom" in content

    def test_write_markdown_contains_table(
        self, sample_results: list[BenchResult]
    ) -> None:
        md = write_markdown(sample_results)
        assert "sre_logs" in md
        assert "raw" in md
        assert "headroom" in md
        assert "70%" in md
        assert "---" in md

    def test_write_markdown_error_shown(self) -> None:
        results = [
            BenchResult(
                adapter="broken",
                dataset="test",
                category="test",
                tokenizer_name="cl100k_base",
                tokens_before=100,
                tokens_after=100,
                tokens_saved_pct=0.0,
                chars_before=400,
                chars_after=400,
                latency_ms=0.0,
                reversible=None,
                error="adapter not available",
            ),
        ]
        md = write_markdown(results)
        assert "err" in md
        assert "adapter not available" in md

    def test_write_markdown_aggregate_table(
        self, sample_results: list[BenchResult]
    ) -> None:
        md = write_markdown(sample_results)
        assert "AGGREGATE" in md

    def test_write_coverage_heatmap(self) -> None:
        results = [
            BenchResult(
                adapter="raw", dataset="d1", category="numeric",
                tokenizer_name="cl100k_base", tokens_before=100,
                tokens_after=100, tokens_saved_pct=0.0,
                chars_before=400, chars_after=400, latency_ms=0.0,
                reversible=True,
            ),
            BenchResult(
                adapter="numeric-fold", dataset="d1", category="numeric",
                tokenizer_name="cl100k_base", tokens_before=100,
                tokens_after=40, tokens_saved_pct=60.0,
                chars_before=400, chars_after=160, latency_ms=1.0,
                reversible=True,
            ),
            BenchResult(
                adapter="raw", dataset="d2", category="agent",
                tokenizer_name="cl100k_base", tokens_before=200,
                tokens_after=200, tokens_saved_pct=0.0,
                chars_before=800, chars_after=800, latency_ms=0.0,
                reversible=True,
            ),
            BenchResult(
                adapter="numeric-fold", dataset="d2", category="agent",
                tokenizer_name="cl100k_base", tokens_before=200,
                tokens_after=180, tokens_saved_pct=10.0,
                chars_before=800, chars_after=720, latency_ms=1.0,
                reversible=True,
            ),
        ]
        heatmap = write_coverage_heatmap(results)
        assert "Coverage Heatmap" in heatmap
        assert "numeric" in heatmap
        assert "agent" in heatmap
        assert "numeric-fold" in heatmap
        assert "60%" in heatmap

    def test_write_fairness_header(self, sample_results: list[BenchResult]) -> None:
        header = write_fairness_header(sample_results)
        assert "Benchmark Report" in header
        assert "Commit" in header
        assert "cl100k_base" in header
        assert "Reproduce" in header


# ---- CLI -------------------------------------------------------------------


class TestCLI:
    def test_run_numeric_suite(self) -> None:
        from click.testing import CliRunner
        from headroom.bench.__main__ import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--suite", "numeric"])
        assert result.exit_code == 0
        assert "sre_logs" in result.output
        assert "geo_search" in result.output
        assert "metrics_timeseries" in result.output

    def test_run_with_csv_output(self, tmp_path: pytest.TempPathFactory) -> None:
        from click.testing import CliRunner
        from headroom.bench.__main__ import cli

        csv_path = str(tmp_path / "results.csv")
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--suite", "adversarial", "--csv", csv_path])
        assert result.exit_code == 0
        content = (tmp_path / "results.csv").read_text()
        assert "adversarial_floats" in content

    def test_run_dual_tokenizer(self) -> None:
        from click.testing import CliRunner
        from headroom.bench.__main__ import cli

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", "--suite", "adversarial", "--tokenizer", "cl100k_base",
             "--tokenizer", "o200k_base"],
        )
        assert result.exit_code == 0
        assert "cl100k_base" in result.output
        assert "o200k_base" in result.output


# ---- _types ----------------------------------------------------------------


class TestTypes:
    def test_dataset_checksum_auto(self) -> None:
        ds = Dataset(
            name="t",
            category="test",
            raw_json='{"a":1}',
            records=[{"a": 1}],
        )
        assert len(ds.checksum) == 16

    def test_suite_config_defaults(self) -> None:
        cfg = SuiteConfig()
        assert cfg.suites == ["all"]
        assert cfg.tokenizers == ["cl100k_base"]
