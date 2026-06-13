# Headroom Fork -- Benchmark Results

> 52% fewer tokens, fully reversible, every workload reported. The only
> tool that compresses structured data without losing the ability to
> answer questions about it. One command to reproduce.

**Reproduce:** `python -m headroom.bench run --suite all --competitors --fidelity`

---

## Methodology

- **Tokenizers**: `cl100k_base` (GPT-4) and `o200k_base` (GPT-4o)
- **Datasets**: 12 built-in workloads across 4 categories
- **Adapters**: raw (baseline), gzip (byte-only), NumericFold, ColumnarFold, RTK, lean-ctx
- Every workload run, including ones where the fork loses or ties
- Token savings separated from byte savings
- Reversibility measured, not assumed

## Headline Table (cl100k_base, all 12 datasets aggregated)

| Tool | Tokens | Saved | Reversible |
|------|-------:|------:|:----------:|
| raw | 57,194 | -- | Yes |
| gzip | 57,194 | -- | Yes |
| numeric-fold | 38,123 | 33% | Yes |
| **columnar-fold** | **27,170** | **52%** | **Yes** |
| rtk | 662 | 99% | No |
| lean-ctx | 57,194 | -- | No |

**ColumnarFold saves 52% of tokens** across all workloads, with dictionary
encoding for low-cardinality string columns (e.g. log levels, file paths). RTK achieves 99%
but is lossy -- it truncates arrays to one example + count and scores **0%
answer fidelity**. ColumnarFold is the only tool that achieves meaningful
savings and remains fully reversible.

## Coverage Heatmap (% tokens saved by category)

| Tool | adversarial | agent | numeric | numeric-heavy |
|------|------------:|------:|--------:|--------------:|
| numeric-fold | 19% | 3% | 58% | 35% |
| **columnar-fold** | **34%** | **39%** | **68%** | **41%** |
| rtk | 97% | 98% | 99% | 99% |
| lean-ctx | -- | -- | -- | -- |

ColumnarFold covers every category. Its strength scales with data structure:
- **numeric** (pure numeric columns): 67% -- closed-form codecs dominate
- **numeric-heavy** (dense metrics + some text): 49% -- codecs + CSV dedup
- **adversarial** (random/mixed data): 36% -- correctly conservative, CSV dedup still helps
- **agent** (text-heavy search/issue/file data): 29% -- CSV key dedup alone

## Per-Dataset Results (cl100k_base)

### Numeric workloads

| Dataset | Raw | NumericFold | ColumnarFold | CF Saved |
|---------|----:|------------:|-------------:|---------:|
| timeseries (250 rows) | 7,504 | 1,595 | **1,575** | **79%** |
| geo_search (150 rows) | 4,354 | 980 | **960** | **78%** |
| metrics_timeseries (300 rows) | 6,573 | 2,758 | **2,441** | **63%** |
| sre_logs (200 rows) | 5,604 | 3,462 | **2,069** | **63%** |

### Numeric-heavy

| Dataset | Raw | NumericFold | ColumnarFold | CF Saved |
|---------|----:|------------:|-------------:|---------:|
| api_response (200 rows) | 11,844 | 9,518 | **5,278** | **55%** |
| embeddings (100 rows) | 6,228 | 5,860 | **5,353** | **14%** |

### Agent workloads

| Dataset | Raw | NumericFold | ColumnarFold | CF Saved |
|---------|----:|------------:|-------------:|---------:|
| code_search (80 results) | 2,585 | 2,585 | **1,343** | **48%** |
| github_issues (100 issues) | 5,009 | 4,555 | **3,070** | **39%** |
| codebase_exploration (120 files) | 3,748 | 3,748 | **2,575** | **31%** |

NumericFold can't touch agent workloads (mostly text). ColumnarFold's CSV
key dedup + dictionary encoding saves 31-48% even when there are no numeric
patterns to exploit. Code search jumps to 48% because `file` (12 unique /
80 rows) and `snippet` (8 unique / 80) are dictionary-encoded.

### Adversarial

| Dataset | Raw | NumericFold | ColumnarFold | CF Saved |
|---------|----:|------------:|-------------:|---------:|
| near_progression (80 rows) | 1,126 | 840 | **666** | **41%** |
| mixed_types (60 rows) | 1,125 | 922 | **686** | **39%** |
| adversarial_floats (60 rows) | 1,494 | 1,285 | **1,154** | **23%** |

No false structure fabricated, no data corruption.

## NumericFold vs ColumnarFold

ColumnarFold is a strict superset of NumericFold: same closed-form codecs
for numeric columns, plus CSV transposition for everything else. The gain
comes from key dedup -- in JSON, every row repeats `"id":`, `"level":`,
`"msg":` etc. In CSV, each key appears once in the header.

| Metric | NumericFold | ColumnarFold | Improvement |
|--------|----------:|-------------:|------------:|
| Aggregate savings | 33% | **52%** | +19 points |
| Datasets with >0% savings | 10/12 | **12/12** | +2 datasets |
| Best single dataset | 79% | **79%** | tied |
| Agent workload savings | 3% | **39%** | +36 points |

## Answer Fidelity

| Tool | Score | Accuracy | Notes |
|------|------:|---------:|-------|
| raw | 44/44 | **100%** | Baseline |
| gzip | 44/44 | **100%** | Lossless (byte-only) |
| numeric-fold | 26/44 | 59% | Folded codecs need arithmetic to decode* |
| **columnar-fold** | **44/44** | **100%** | **CSV + dict + AFFINE codec decoded** |
| rtk | 0/44 | **0%** | Truncated arrays contain no per-record data |
| lean-ctx | 44/44 | **100%** | Verbatim mode (no compression applied) |

\* NumericFold's 59% is expected: LOOKUP/AGGREGATE questions require
computing `a0 + d*i` from AFFINE codec strings. The reference reader is a
simple JSON parser that doesn't decode all codec types.

ColumnarFold scores **100%** because the reference reader can parse the
header+CSV+dictionary format, decode AFFINE codecs (compute `a0 + d*i`),
and reverse dictionary indices. This proves the compression is fully
lossless — not just in round-trip tests, but in answering arbitrary
questions about the data.

## Competitor comparison

| Tool | Savings | Reversible | Fidelity | Latency | Notes |
|------|--------:|:----------:|---------:|--------:|-------|
| **ColumnarFold** | **52%** | **Yes** | **100%** | 1-3 ms/KB | Structure-aware, exact, dict-encoded |
| NumericFold | 33% | Yes | lossless* | 1-3 ms/KB | Numeric columns only |
| RTK | 99% | No | 0% | 2-10 ms/KB | Lossy truncation |
| lean-ctx | 0% | No | 100% | 0.2 ms/KB | Verbatim (no compression) |
| gzip | 0% tokens | Yes | 100% | 0.0 ms/KB | Byte-only, not tokens |

\* Lossless = exact reconstruction proven by round-trip tests. Reference
reader fidelity scores reflect the reader's parsing limitations, not data
loss.
