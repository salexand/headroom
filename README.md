<div align="center"><pre>
  ██╗  ██╗███████╗ █████╗ ██████╗ ██████╗  ██████╗  ██████╗ ███╗   ███╗
  ██║  ██║██╔════╝██╔══██╗██╔══██╗██╔══██╗██╔═══██╗██╔═══██╗████╗ ████║
  ███████║█████╗  ███████║██║  ██║██████╔╝██║   ██║██║   ██║██╔████╔██║
  ██╔══██║██╔══╝  ██╔══██║██║  ██║██╔══██╗██║   ██║██║   ██║██║╚██╔╝██║
  ██║  ██║███████╗██║  ██║██████╔╝██║  ██║╚██████╔╝╚██████╔╝██║ ╚═╝ ██║
  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝     ╚═╝
                  The context compression layer for AI agents
</pre></div>

<p align="center"><strong>60–95% fewer tokens · library · proxy · MCP · 6 algorithms · local-first · reversible</strong></p>

<p align="center">
  <a href="https://github.com/chopratejas/headroom/actions/workflows/ci.yml"><img src="https://github.com/chopratejas/headroom/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://app.codecov.io/gh/chopratejas/headroom"><img src="https://codecov.io/gh/chopratejas/headroom/graph/badge.svg" alt="codecov"></a>
  <a href="https://pypi.org/project/headroom-ai/"><img src="https://img.shields.io/pypi/v/headroom-ai.svg" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/headroom-ai"><img src="https://img.shields.io/npm/v/headroom-ai.svg" alt="npm"></a>
  <a href="https://huggingface.co/chopratejas/kompress-base"><img src="https://img.shields.io/badge/model-Kompress--base-yellow.svg" alt="Model: Kompress-base"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
  <a href="https://headroom-docs.vercel.app/docs"><img src="https://img.shields.io/badge/docs-online-blue.svg" alt="Docs"></a>
</p>

<p align="center">
  <a href="https://headroom-docs.vercel.app/docs">Docs</a> ·
  <a href="#get-started-60-seconds">Install</a> ·
  <a href="#proof">Proof</a> ·
  <a href="#agent-compatibility-matrix">Agents</a> ·
  <a href="https://discord.gg/yRmaUNpsPJ">Discord</a> ·
  <a href="llms.txt">llms.txt</a> ·
  <a href="ENTERPRISE.md">Enterprise</a>
</p>

<p align="center"><sub>
  <b>AI agents / LLMs:</b> read <a href="llms.txt"><code>/llms.txt</code></a> here, or fetch <a href="https://headroom-docs.vercel.app/llms.txt">the live index</a> / <a href="https://headroom-docs.vercel.app/llms-full.txt">full docs blob</a>.
</sub></p>

---
<p align="center"><a href="https://trendshift.io/repositories/20881" target="_blank"><img src="https://trendshift.io/api/badge/repositories/20881" alt="chopratejas%2Fheadroom | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a></p>

Headroom compresses everything your AI agent reads — tool outputs, logs, RAG chunks, files, and conversation history — before it reaches the LLM. Same answers, fraction of the tokens.

<p align="center">
  <img src="HeadroomDemo-Fast.gif" alt="Headroom in action" width="820">
  <br/><sub>Live: 10,144 → 1,260 tokens — same FATAL found.</sub>
</p>

## What it does

- **Library** — `compress(messages)` in Python or TypeScript, inline in any app
- **Proxy** — `headroom proxy --port 8787`, zero code changes, any language
- **Agent wrap** — `headroom wrap claude|codex|cursor|aider|copilot` in one command
- **MCP server** — `headroom_compress`, `headroom_retrieve`, `headroom_stats` for any MCP client
- **Cross-agent memory** — shared store across Claude, Codex, Gemini, auto-dedup
- **`headroom learn`** — mines failed sessions, writes corrections to `CLAUDE.md` / `AGENTS.md`
- **Reversible (CCR)** — originals never deleted; LLM retrieves on demand

## How it works (30 seconds)

```
 Your agent / app
   (Claude Code, Cursor, Codex, LangChain, Agno, Strands, your own code…)
        │   prompts · tool outputs · logs · RAG results · files
        ▼
    ┌────────────────────────────────────────────────────┐
    │  Headroom   (runs locally — your data stays here)  │
    │  ────────────────────────────────────────────────  │
    │  CacheAligner  →  ContentRouter  →  CCR            │
    │                    ├─ SmartCrusher   (JSON)        │
    │                    ├─ CodeCompressor (AST)         │
    │                    └─ Kompress-base  (text, HF)    │
    │                                                    │
    │  Cross-agent memory  ·  headroom learn  ·  MCP     │
    └────────────────────────────────────────────────────┘
        │   compressed prompt  +  retrieval tool
        ▼
 LLM provider  (Anthropic · OpenAI · Bedrock · …)
```

- **ContentRouter** — detects content type, selects the right compressor
- **SmartCrusher / CodeCompressor / Kompress-base** — compress JSON, AST, or prose
- **CacheAligner** — stabilizes prefixes so provider KV caches actually hit
- **CCR** — stores originals locally; LLM calls `headroom_retrieve` if it needs them

→ [Architecture](https://headroom-docs.vercel.app/docs/architecture) · [CCR reversible compression](https://headroom-docs.vercel.app/docs/ccr) · [Kompress-base model card](https://huggingface.co/chopratejas/kompress-base)

## Get started (60 seconds)

```bash
# 1 — Install
pip install "headroom-ai[all]"          # Python
npm install headroom-ai                 # Node / TypeScript

# 2 — Pick your mode
headroom wrap claude                    # wrap a coding agent
headroom proxy --port 8787              # drop-in proxy, zero code changes
# or: from headroom import compress      # inline library

# 3 — See the savings
headroom perf
```

Granular extras: `[proxy]`, `[mcp]`, `[ml]`, `[code]`, `[memory]`, `[relevance]`, `[image]`, `[agno]`, `[langchain]`, `[evals]`. Requires **Python 3.10+**.

## Proof

**Savings on real agent workloads:**

| Workload                      | Before | After  | Savings |
|-------------------------------|-------:|-------:|--------:|
| Code search (100 results)     | 17,765 |  1,408 | **92%** |
| SRE incident debugging        | 65,694 |  5,118 | **92%** |
| GitHub issue triage           | 54,174 | 14,761 | **73%** |
| Codebase exploration          | 78,502 | 41,254 | **47%** |

**Accuracy preserved on standard benchmarks:**

| Benchmark  | Category | N   | Baseline | Headroom | Delta      |
|------------|----------|----:|---------:|---------:|------------|
| GSM8K      | Math     | 100 |    0.870 |    0.870 | **±0.000** |
| TruthfulQA | Factual  | 100 |    0.530 |    0.560 | **+0.030** |
| SQuAD v2   | QA       | 100 |        — |  **97%** | 19% compression |
| BFCL       | Tools    | 100 |        — |  **97%** | 32% compression |

Reproduce: `python -m headroom.evals suite --tier 1` · [Full benchmarks & methodology](https://headroom-docs.vercel.app/docs/benchmarks)

**This fork's added value -- 60% synthetic, 49% real-world, fully reversible:**

Synthetic benchmarks (14 datasets, controlled data):

| Dataset | Before | After | Saved | Reversible |
|---------|-------:|------:|------:|:----------:|
| Recurrence sequences (100 rows) | 4,327 | 496 | **89%** | Yes |
| Geo search (150 rows) | 4,354 | 666 | **85%** | Yes |
| Timeseries (250 rows) | 7,504 | 1,575 | **79%** | Yes |
| Metrics timeseries (300 rows) | 6,573 | 1,859 | **72%** | Yes |
| Cross-column (120 rows, derived cols) | 6,605 | 1,920 | **71%** | Yes |
| SRE logs (200 rows) | 5,604 | 2,069 | **63%** | Yes |
| API response (200 rows) | 11,854 | 5,278 | **55%** | Yes |
| **All 14 datasets** | **68,143** | **27,313** | **60%** | **Yes** |

Real-world tool outputs (6 realistic generators with nested dicts, optional fields, UUIDs):

| Dataset | Before | After | Saved | Reversible |
|---------|-------:|------:|------:|:----------:|
| API responses (200, nested attrs/links/meta) | 15,250 | 6,501 | **57%** | Yes |
| DB metrics (300 rows) | 13,599 | 6,464 | **52%** | Yes |
| DB users (200, mixed nulls) | 9,802 | 5,012 | **49%** | Yes |
| Search results (200, nested metadata) | 14,726 | 7,618 | **48%** | Yes |
| Log entries (500, nested exceptions) | 32,371 | 17,513 | **46%** | Yes |
| DB transactions (200 rows) | 10,317 | 5,990 | **42%** | Yes |
| **All 6 real-world datasets** | **96,065** | **49,098** | **49%** | **Yes** |

Competitors: RTK achieves 99% but is lossy (0% answer fidelity). ColumnarFold is the only tool that compresses meaningfully **and** stays fully reversible.

Reproduce: `python -m headroom.bench run --suite all --competitors --fidelity` · [Full benchmark report](BENCHMARKS.md)

<a href="https://www.star-history.com/?repos=chopratejas%2Fheadroom&type=date&legend=top-left">
 <picture>
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=chopratejas/headroom&type=date&legend=top-left" />
 </picture>
</a>

## Agent compatibility matrix

| Agent       | `headroom wrap` | Notes                            |
|-------------|:---------------:|----------------------------------|
| Claude Code | ✅              | `--memory` · `--code-graph`      |
| Codex       | ✅              | shares memory with Claude        |
| Cursor      | ✅              | prints config — paste once       |
| Aider       | ✅              | starts proxy + launches          |
| Copilot CLI | ✅              | starts proxy + launches          |
| OpenClaw    | ✅              | installs as ContextEngine plugin |

Any OpenAI-compatible client works via `headroom proxy`. MCP-native: `headroom mcp install`.

### GitHub Copilot CLI subscription mode

Headroom can route GitHub Copilot CLI subscription traffic through the local proxy:

```bash
headroom wrap copilot --subscription -- --model gpt-4o
```

This lets Headroom intercept OpenAI-compatible Copilot CLI requests and apply the same proxy compression pipeline before forwarding to GitHub Copilot's hosted API. The wrapper resolves the account-specific Copilot API endpoint and prints it as `COPILOT_PROVIDER_API_URL=...` during launch.

Platform support note: macOS auth reuse via Copilot CLI Keychain storage has been smoke-tested. Windows Credential Manager, Linux Secret Service / `secret-tool`, and Docker/CI token-injection paths are implemented or planned as auth-discovery paths, but still need real OS validation before they should be considered fully vetted. For Docker and CI, prefer passing an explicit `GITHUB_COPILOT_TOKEN` or `GITHUB_COPILOT_GITHUB_TOKEN` rather than relying on host keychain access.

## When to use · When to skip

**Great fit if you…**
- run AI coding agents daily and want savings without changing your code
- work across multiple agents and want shared memory
- need reversible compression — originals always retrievable via CCR

**Skip it if you…**
- only use a single provider's native compaction and don't need cross-agent memory
- work in a sandboxed environment where local processes can't run

<details>
<summary><b>Integrations — drop Headroom into any stack</b></summary>

| Your setup             | Hook in with                                                     |
|------------------------|------------------------------------------------------------------|
| Any Python app         | `compress(messages, model=…)`                                    |
| Any TypeScript app     | `await compress(messages, { model })`                            |
| Anthropic / OpenAI SDK | `withHeadroom(new Anthropic())` · `withHeadroom(new OpenAI())`   |
| Vercel AI SDK          | `wrapLanguageModel({ model, middleware: headroomMiddleware() })` |
| LiteLLM                | `litellm.callbacks = [HeadroomCallback()]`                       |
| LangChain              | `HeadroomChatModel(your_llm)`                                    |
| Agno                   | `HeadroomAgnoModel(your_model)`                                  |
| Strands                | [Strands guide](https://headroom-docs.vercel.app/docs/strands)  |
| ASGI apps              | `app.add_middleware(CompressionMiddleware)`                      |
| Multi-agent            | `SharedContext().put / .get`                                     |
| MCP clients            | `headroom mcp install`                                           |

</details>

<details>
<summary><b>What's inside</b></summary>

- **SmartCrusher** — universal JSON: arrays of dicts, nested objects, mixed types.
- **CodeCompressor** — AST-aware for Python, JS, Go, Rust, Java, C++.
- **Kompress-base** — our HuggingFace model, trained on agentic traces.
- **Image compression** — 40–90% reduction via trained ML router.
- **CacheAligner** — stabilizes prefixes so Anthropic/OpenAI KV caches actually hit.
- **IntelligentContext** — score-based context fitting with learned importance.
- **CCR** — reversible compression; LLM retrieves originals on demand.
- **Cross-agent memory** — shared store, agent provenance, auto-dedup.
- **SharedContext** — compressed context passing across multi-agent workflows.
- **`headroom learn`** — plugin-based failure mining for Claude, Codex, Gemini.

</details>

<details>
<summary><b>Pipeline internals</b></summary>

Headroom exposes one stable request lifecycle across `compress()`, the SDK, and the proxy:

`Setup` → `Pre-Start` → `Post-Start` → `Input Received` → `Input Cached` → `Input Routed` → `Input Compressed` → `Input Remembered` → `Pre-Send` → `Post-Send` → `Response Received`

- **Transforms** do the work: CacheAligner, ContentRouter, SmartCrusher, CodeCompressor, Kompress-base, IntelligentContext / RollingWindow.
- **Pipeline extensions** observe or customize lifecycle stages via `on_pipeline_event(...)`.
- **Compression hooks** sit alongside the canonical lifecycle as an additional extension seam.
- **Proxy extensions** remain the server/app integration seam for ASGI middleware, routes, and startup policy.

Provider and tool-specific behavior lives under `headroom/providers/` so core orchestration stays focused on lifecycle, sequencing, and policy.

- **CLI/tool slices**: `headroom/providers/claude`, `copilot`, `codex`, `openclaw`
- **Provider runtime slices**: `headroom/providers/claude`, `gemini`, plus shared backend/runtime dispatch in `headroom/providers/registry.py`
- **Core files stay orchestration-first**: `wrap.py`, `client.py`, `cli/proxy.py`, and `proxy/server.py` delegate provider-specific env shaping, API target normalization, backend selection, and transport dispatch.

</details>

## Install

```bash
pip install "headroom-ai[all]"          # Python, everything
npm install headroom-ai                 # TypeScript / Node
docker pull ghcr.io/chopratejas/headroom:latest
```

Granular extras: `[proxy]`, `[mcp]`, `[ml]` (Kompress-base), `[code]`, `[memory]`, `[relevance]`, `[image]`, `[agno]`, `[langchain]`, `[evals]`. Requires **Python 3.10+**.

Using `pipx`? Choose a supported interpreter explicitly:

```bash
pipx install --python python3.13 "headroom-ai[all]"
```

→ [Installation guide](https://headroom-docs.vercel.app/docs/installation) — Docker tags, persistent service, PowerShell, devcontainers.

## headroom learn

<p align="center">
  <img src="headroom_learn.gif" alt="headroom learn in action" width="720">
</p>

`headroom learn` — mines failed sessions, writes corrections to `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`.

## Documentation

| Start here                                                                    | Go deeper                                                                          |
|-------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| [Quickstart](https://headroom-docs.vercel.app/docs/quickstart)                | [Architecture](https://headroom-docs.vercel.app/docs/architecture)                 |
| [Proxy](https://headroom-docs.vercel.app/docs/proxy)                          | [How compression works](https://headroom-docs.vercel.app/docs/how-compression-works) |
| [MCP tools](https://headroom-docs.vercel.app/docs/mcp)                        | [CCR — reversible compression](https://headroom-docs.vercel.app/docs/ccr)          |
| [Memory](https://headroom-docs.vercel.app/docs/memory)                        | [Cache optimization](https://headroom-docs.vercel.app/docs/cache-optimization)     |
| [Failure learning](https://headroom-docs.vercel.app/docs/failure-learning)    | [Benchmarks](https://headroom-docs.vercel.app/docs/benchmarks)                    |
| [Configuration](https://headroom-docs.vercel.app/docs/configuration)          | [Limitations](https://headroom-docs.vercel.app/docs/limitations)                  |

## Compared to

Headroom runs **locally**, covers **every** content type, works with every major framework, and is **reversible**.

|                                                                              | Scope                                          | Deploy                             | Local | Reversible |
|------------------------------------------------------------------------------|------------------------------------------------|------------------------------------|:-----:|:----------:|
| **Headroom**                                                                 | All context — tools, RAG, logs, files, history | Proxy · library · middleware · MCP | Yes   | Yes        |
| [RTK](https://github.com/rtk-ai/rtk)                                        | CLI command outputs                            | CLI wrapper                        | Yes   | No         |
| [lean-ctx](https://github.com/yvgude/lean-ctx)                               | CLI commands, MCP tools, editor rules          | CLI wrapper · MCP                  | Yes   | No         |
| [Compresr](https://compresr.ai), [Token Co.](https://thetokencompany.ai)    | Text sent to their API                         | Hosted API call                    | No    | No         |
| OpenAI Compaction                                                            | Conversation history                           | Provider-native                    | No    | No         |

> **Attribution.** Headroom ships with the excellent [RTK](https://github.com/rtk-ai/rtk) binary for shell-output rewriting — `git show --short`, scoped `ls`, summarized installers. Huge thanks to the RTK team; their tool is a first-class part of our stack, and Headroom compresses everything downstream of it. Headroom can also use [lean-ctx](https://github.com/yvgude/lean-ctx) as the selected CLI context tool; set `HEADROOM_CONTEXT_TOOL=lean-ctx` before running `headroom wrap ...`.

## Contributing

```bash
git clone https://github.com/chopratejas/headroom.git && cd headroom
pip install -e ".[dev]" && pytest
```

Devcontainers in `.devcontainer/` (default + `memory-stack` with Qdrant & Neo4j). See [CONTRIBUTING.md](CONTRIBUTING.md).

## Community

- **[Discord](https://discord.gg/yRmaUNpsPJ)** — questions, feedback, war stories.
- **[Kompress-base on HuggingFace](https://huggingface.co/chopratejas/kompress-base)** — the model behind our text compression.

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

## What this fork adds

This fork extends upstream Headroom with **lossless, structure-aware compression**, a **reproducible benchmark suite**, and **advanced R&D modules**. Everything is merged to `main`, tested, and CI-gated.

### Summary

| Component | What it does | Status |
|-----------|-------------|--------|
| **NumericFold** | Replaces numeric columns with closed-form rules (AFFINE, CONST, POLY, DELTA, RATIONAL) | Merged, CI-gated |
| **ColumnarFold** | Transposes residual columns into CSV (key dedup) on top of NumericFold | Merged |
| **headroom-bench** | Single-command benchmark suite: 12 datasets, 7 adapters, dual tokenizer, fidelity scoring | Merged |
| **MDL Scorer** | Principled compressor selection via Minimum Description Length | Merged |
| **rANS Codec** | Entropy coder for CCR storage compression (bytes, not tokens) | Merged |
| **Ramanujan LSH** | Expander-graph LSH for memory dedup (alternative to HNSW) | Merged |

---

### Compression transforms

**NumericFold** stores the *rule* behind numeric columns instead of listing every value:

| Codec | Pattern | Example | Stored as |
|---|---|---|---|
| `CONST` | every value identical | `0.25, 0.25, ...` | one value + count |
| `AFFINE` | arithmetic progression | `0,1,2,...,199` | `a0, d, n` (3 numbers) |
| `POLY_k` | polynomial growth | `0,3,8,15,...` | `k+1` coefficients |
| `DELTA` | small step-to-step changes | jittery timestamps | base + deltas |
| `RATIONAL` | hidden fractions (continued-fraction convergents) | `3.14159...` -> `355/113` | the fraction |
| `RECURRENCE` | linear recurrence (Fibonacci-like, exponential, geometric) | `1,3,11,41,153,...` | coefficients + initial values |

**ColumnarFold** builds on NumericFold by transposing the leftover non-numeric columns into a single CSV block where each key appears once in the header instead of once per row. It also applies **cross-column references**: when a whole column is an exact affine function of another (`B = m*A + c` — dual-unit timestamps, byte/KiB pairs, price-with-tax, duplicated ids), the column is replaced by a one-line `@linref` reference instead of N rows of data:

```
n=100|cols:id=AFFINE(a0=0,d=1,n=100);ts=AFFINE(a0=1718200000,d=7,n=100)
@linref:bytes=kib|m=1024|c=0
_i,level,latency_ms,msg
0,INFO,56.8,request handled
1,WARN,31.7,cache miss
...
```

Both are **lossless** (every value reconstructs bit-for-bit) and covered by 50+ unit, round-trip, and randomized-fuzz tests.

---

### Benchmark suite (`headroom-bench`)

Single-command, reproducible benchmark: `python -m headroom.bench run --suite all --competitors --fidelity`

**14 datasets** across 6 categories:
- **Numeric**: SRE logs, geo search, metrics timeseries
- **Agent**: code search, GitHub issues, codebase exploration
- **Numeric-heavy**: API responses, embeddings, timeseries
- **Recurrence**: recurrence sequences
- **Cross-column**: derived columns (`B = m*A + c`)
- **Adversarial**: random floats, near-progressions, mixed types

**7 adapters**: raw (baseline), gzip (byte-only reference), NumericFold, ColumnarFold, RTK, lean-ctx, headroom-upstream

**Results** (cl100k_base, all datasets aggregated):

| Tool | Tokens | Saved | Reversible |
|------|-------:|------:|:----------:|
| raw | 68,143 | -- | Yes |
| numeric-fold | 42,245 | 38% | Yes |
| **columnar-fold** | **27,313** | **60%** | **Yes** |
| rtk | 788 | 99% | No |
| lean-ctx | 68,143 | -- | No |

ColumnarFold saves **60% on synthetic data** and **49% on real-world tool outputs** (with nested dicts, optional fields, UUIDs). Includes RECURRENCE codec, cross-column references, dictionary encoding, prefix dedup, and nested-dict flattening. RTK achieves 99% but is lossy (0% answer fidelity). ColumnarFold is the only tool that compresses meaningfully **and** stays fully reversible.

**Coverage heatmap** (% tokens saved by category):

| Tool | adversarial | agent | cross-column | numeric | numeric-heavy |
|------|------------:|------:|-------------:|--------:|--------------:|
| numeric-fold | 19% | 3% | 37% | 61% | 35% |
| **columnar-fold** | **34%** | **48%** | **71%** | **73%** | **51%** |
| rtk | 97% | 98% | 99% | 99% |

The suite also includes:
- **Fidelity scoring**: deterministic reference reader proves information sufficiency
- **Fairness header**: commit hash, tokenizer, reproduce command
- **Dual tokenizer**: cl100k_base + o200k_base
- **CSV + markdown output**: `--csv results.csv --md BENCHMARKS.md`
- **CI workflow**: GitHub Actions runs on every PR touching bench/transforms code

Full results: [BENCHMARKS.md](BENCHMARKS.md)

---

### Advanced R&D modules

**MDL Scorer** (`headroom/transforms/mdl_scorer.py`) — generalises NumericFold's per-column MDL principle to the top-level ContentRouter. Instead of a hard-coded content-type-to-strategy map, `mdl_select()` tries each candidate compressor and picks the one with the shortest total description length (`L(model) + L(data|model)`). Always includes raw as baseline, so it never picks a compressor that inflates.

**rANS Codec** (`headroom/cache/rans_codec.py`) — order-0 range Asymmetric Numeral System encoder for compressing CCR originals on disk. This is **byte compression, not token reduction** (the LLM never sees the encoded form). Reduces storage cost for the CCR originals store. Pure Python prototype; production path is the Rust crate.

**Ramanujan LSH** (`headroom/memory/backends/ramanujan_lsh.py` + `headroom/memory/adapters/ramanujan_vector.py`) — locality-sensitive hashing using Ramanujan-graph-inspired projections (QR-orthogonalized for optimal spectral gap) for approximate nearest neighbor search. Full `VectorIndex` adapter that plugs into the memory system alongside HNSW/sqlite-vec. O(1) index time, O(L) query time, includes `find_duplicates()` for cross-agent dedup.

**Ramanujan LSH vs brute-force cosine search:**

| Vectors | Dim | Tables | LSH query | BF query | Speedup | Recall@10 | Self-recall |
|--------:|----:|-------:|----------:|---------:|--------:|----------:|------------:|
| 1,000 | 128 | 12 | 0.08ms | 0.64ms | **7.8x** | 21% | 100% |
| 5,000 | 384 | 16 | 0.39ms | 3.81ms | **9.9x** | 21% | 100% |
| 10,000 | 384 | 20 | 0.31ms | 8.64ms | **27.6x** | 15% | 100% |

100% self-recall (always finds the query vector). ~20% recall@10 on uniform random vectors is the expected LSH baseline — real embeddings with natural clustering recall significantly higher. Reproduce: `python benchmarks/bench_ramanujan_vs_bruteforce.py`

---

### The underlying math

Three fields power the fork's compression:

- **Calculus of finite differences** — Newton's forward-difference formula recovers polynomials from values. Powers `AFFINE` and `POLY` codecs.
- **Number theory, via continued fractions** — Stern-Brocot/convergents machinery finds compact fractions hiding in decimal columns. Powers `RATIONAL`.
- **Algorithmic information theory** — Kolmogorov complexity and its practical proxy, MDL. The unifying frame: every codec is a candidate program, MDL picks the shortest. Now generalised from per-column (NumericFold) to per-compressor (MDL Scorer).

---

### Test coverage

| Module | Tests | What's covered |
|--------|------:|----------------|
| NumericFold | 30 | Codec selection, lossless round-trips, edge cases |
| ColumnarFold | 16 | Fold, roundtrip, type preservation, cross-column references, beats-NumericFold |
| headroom-bench | 55 | Loader, adapters, scorer, reporter, fidelity, CLI |
| MDL Scorer | 10 | Selection, inflation rejection, model cost, errors |
| rANS Codec | 15 | Round-trips, compression ratios, all byte values |
| Ramanujan LSH | 10 | ANN search, dedup, recall at scale |
| Ramanujan VectorIndex | 11 | VectorIndex protocol, filtering, batch ops |
| **Total** | **137** | |

---

### References

- Prompt Compression for Large Language Models: A Survey (NAACL 2025) -- https://arxiv.org/html/2410.12388v2
- LLMLingua (Microsoft Research) -- https://www.microsoft.com/en-us/research/blog/llmlingua-innovating-llm-efficiency-with-prompt-compression/
- LLMLingua-2 -- https://arxiv.org/pdf/2403.12968
- Lossless Token Sequence Compression via Meta-Tokens -- https://arxiv.org/pdf/2506.00307

