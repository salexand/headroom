## Context for this session

You're working on a fork of Headroom (github.com/salexand/headroom) — an LLM context compression system. This fork adds structure-aware lossless compression that saves 58% of tokens on synthetic data and 49% on real-world tool outputs, vs 0% from upstream on the same workloads.

### What's been built (72 PRs merged)

**Compression pipeline (all on by default):**
- ColumnarFold — CSV key dedup, closed-form numeric codecs (AFFINE/CONST/POLY/DELTA/RATIONAL/RECURRENCE), dictionary encoding for low-cardinality strings, prefix dedup for timestamps/paths/IDs, nested-dict flattening for scalar-valued nested dicts, nullable types (int?, float?, str?, bool?)
- Threshold: 3 rows / 30 tokens (lowered from 8/80 — even 3-row arrays save 18%)
- MDL Scorer — principled compressor selection wired into ContentRouter
- rANS entropy coder — byte compression for CCR storage
- Ramanujan LSH — multi-probe expander-graph LSH for memory dedup (69% recall at 8 probes)

**Benchmark suite (`python -m headroom.bench run --suite all`):**
- 13 synthetic datasets, 7 adapters, dual tokenizer, fidelity scoring
- 6 real-world tool output generators tested separately
- CI workflow on every PR

**Tooling:**
- `claude-with-headroom.bat` — one-click Claude Code with compression
- `headroom-savings.py` — live savings dashboard (separates RTK filter vs compression savings)
- Launch scripts for Codex, Gemini

**Tests:** 242+ passing (including 102 paranoid lossless tests)

### Current numbers

| Metric | Value |
|--------|------:|
| Synthetic aggregate (13 datasets) | 58% saved |
| Real-world aggregate (6 datasets) | 49% saved |
| Best single dataset | 89% (recurrence sequences) |
| Worst single dataset | 17% (embeddings) |
| Answer fidelity | 100% (ColumnarFold) |
| Latency | 1-3 ms/KB |

### Why some tool outputs don't compress

- **prefix_frozen** — messages in provider's prefix cache. Correct: modifying them invalidates cache, costs more than it saves.
- **too_small** — output below 30 tokens. Now catches 3-row arrays (was 80 tokens / 8 rows).
- **no_compressible_content** — non-JSON outputs (git status, short file reads). These are 20-50 tokens of pure information, not worth compressing.

### What's left to do

1. Residual predict-and-correct codec (would use the Ramanujan trace-unit math)
2. Testing on captured real agent traces
3. Lossy float quantization for embedding-heavy data
4. Cross-column compression (detect col B = f(col A))

### Important rules

- Do NOT contribute code back to chopratejas/headroom (keep fork private)
- The Ramanujan trace-unit paper is confidential unpublished work — never share
- The RECURRENCE codec is generic Berlekamp-Massey, NOT an application of the paper
- Work autonomously — don't pause for routine steps (commits, PRs, merges)

### Quick commands

```
python -m headroom.bench run --suite all              # run benchmarks
python -m pytest tests/ -v                            # run all tests
python headroom-savings.py --once                      # check proxy savings
headroom wrap claude                                   # launch with compression
```
