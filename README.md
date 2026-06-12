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

## Structure-aware compression — what this fork adds

*A brief on what this fork adds over the upstream project, what it measurably buys, how it relates to prior art, and where the math points next.*

---

## TL;DR

This fork adds two **lossless, structure-aware** compression transforms aimed specifically at the JSON tool outputs, logs, and tabular results that dominate an agent's context window:

- **NumericFold** — replaces numeric columns with the *closed-form rule that generates them* (an arithmetic run, a constant, a polynomial, or a hidden fraction). **Merged to `main`.**
- **ColumnarFold** — transposes the leftover non-numeric columns into a single indexed CSV block so each key is paid once instead of once per row. **Validated; PR pending.**

Both are exact (every value reconstructs bit-for-bit). On mixed agent-style workloads they cut **~65–77% of tokens** while *preserving — and in the latest run slightly improving* — answer accuracy versus raw JSON.

The conceptual frame is **algorithmic information theory**: treat compression as "find the shortest program that regenerates this data exactly," and let a Minimum Description Length (MDL) rule pick the shortest candidate per column.

---

## 1. What changed after the fork

Upstream Headroom compresses context with a general-purpose crusher: it shrinks text generically before it reaches the model. What it does **not** do is exploit *structure*. When a tool returns 200 rows of JSON, every row repeats the same keys, and numeric columns frequently follow simple patterns that a generic text compressor cannot recognize.

This fork adds two transforms that target exactly that.

### NumericFold (merged, PR #24)

Instead of listing every value in a numeric column, NumericFold stores the **rule** behind it and reconstructs the values on the way out. It tries several codecs per column and keeps whichever description is shortest:

| Codec | Pattern it captures | Example | Stored as |
|---|---|---|---|
| `CONST` | every value identical | `0.25, 0.25, …` | one value + count |
| `AFFINE` | arithmetic progression | `0,1,2,…,199` | `a0, d, n` (3 numbers) |
| `POLY_k` | polynomial growth (via Newton forward differences) | `0,3,8,15,…` | `k+1` coefficients |
| `DELTA` | small step-to-step changes | jittery timestamps | base + zig-zag deltas |
| `RATIONAL` | decimals that are secretly a clean fraction | `3.1415929…` → `355/113` | the fraction (continued-fraction convergents) |
| `RAW` | no pattern found | arbitrary noise | falls through to ColumnarFold |

`RATIONAL` is the Ramanujan thread: a continued-fraction search recovers the compact fraction hiding inside a column of decimals.

NumericFold is **lossless** and is gated behind an env flag while it ships. It is wired into the pipeline after the existing content router and covered by a CI accuracy gate.

### ColumnarFold (validated, PR pending)

NumericFold leaves the *non-numeric* columns (log levels, messages, hostnames) inline as repeated-key JSON, so those keys are still paid on every row. ColumnarFold collects all the residual columns — RAW numerics plus non-numeric scalars — into a **single CSV block**: the key appears once in the header, and each record becomes one row.

It also prepends an explicit `_i` **row-index column**, so a positional lookup ("the value at index 47") becomes *find the row where `_i = 47`* — a read, not a count into a flat parallel array. That index column is the fix for a legibility dip described in §2.

A folded tool output ends up looking like this:

```
n=100|cols:id=AFFINE(a0=0,d=1,n=100);ts=AFFINE(a0=1718200000,d=7,n=100)
_i,level,latency_ms,msg
0,INFO,56.8,request handled
1,WARN,31.7,cache miss
2,ERROR,44.0,retry scheduled
...
```

The header carries the computed (closed-form) columns; the CSV carries the row-addressed ones. Per-column types are recorded so cells decode back exactly — a zip code `01234` stays a string, `42` stays an int, and mixed/nested values are JSON-encoded per cell. Round-trips are asserted in tests.

---

## 2. The quantified improvements

### NumericFold

Roughly **74% fewer tokens** on numeric columns (measured with real `tiktoken`, not an estimate), lossless, with answer accuracy preserved. The closed-form codecs (`AFFINE`/`CONST`) read neutral-to-slightly-*better* for the model; the riskier `POLY` codec is gated off by default. Merged and CI-gated.

### ColumnarFold — latest live legibility run

The open question was whether the residual columns, once flattened into CSV, stay as legible to a model as raw JSON. The harness scores a model on the **same questions** over the folded output vs. the raw JSON and reports the per-bucket accuracy delta.

The most recent run (`gemini-2.5-flash`, 184 cases, 8 repeats, `tiktoken:cl100k_base`):

**Token savings:** `9321 → 3242` tokens = **65% saved** on this workload mix.

**Information sufficiency (deterministic reference reader):** 184/184 = **100%** — the folded form provably contains everything needed to answer.

**Model legibility (folded vs. raw):**

| Bucket | Folded | Raw | Δ (fold − raw) |
|---|---|---|---|
| AFFINE | 99% (79/80) | 95% (76/80) | **+4%** |
| CONST | 100% (16/16) | 100% (16/16) | +0% |
| POLY2 | 100% (16/16) | 100% (16/16) | +0% *(gated)* |
| **csv** | **100% (48/48)** | **100% (48/48)** | **+0%** |
| structural | 100% (24/24) | 100% (24/24) | +0% |
| **OVERALL** | **99%** | **98%** | **+2%** |

The headline: the `csv` bucket — the one column type at risk — closed from an earlier **−6%** gap to **+0%** once the `_i` index column was added. Overall, the folded form is **not just as legible as raw JSON, it edged it out by +2%**, because the closed-form columns give the model the rule directly instead of making it scan a list.

### ColumnarFold vs. NumericFold (size only)

On larger benchmark workloads, transposing the residual columns saves **+27–32 percentage points** beyond NumericFold alone, for a combined **~73–77%** total reduction. (One aggregate benchmark: 31,257 raw tokens → 8,370.)

> **Honest note on the spread.** The savings figure ranges roughly **65–77%** depending on how compressible a given workload's columns are — highly regular numeric columns fold to almost nothing, while genuinely random string columns only benefit from key-dedup. The 65% above is a smaller, harder mix; the 73–77% is the larger benchmark suite.

**Bottom line:** one improvement (NumericFold) is fully shipped and proven; the second (ColumnarFold) is now built, measured, and legibility-cleared — ready to wire behind its own flag and open as a PR.

---

## 3. Has anyone done this before?

Not in this exact form. The mainstream prompt/context-compression literature is **lossy and statistical**:

- **LLMLingua / LLMLingua-2 / LongLLMLingua** (Microsoft) use a small language model to score each token's "importance" by perplexity and delete the low-value ones. Notably, they include special rules to *protect* numbers from being mangled — a tell that they treat numbers as something to preserve, not a structure to exploit.
- Most of the 2024–2025 survey work covers token-selection/deletion, soft-prompt/KV compression (GIST, ICAE, 500xCompressor), and learned token-merging (e.g., lossless "meta-tokens").

What's distinctive here is the angle: **lossless, structure-aware, closed-form encoding of tabular tool outputs**, where the compression *is* the mathematical pattern in the data rather than a statistical judgment about which words matter. The narrow niche — compressing the *structure* of agent/tool JSON specifically, exactly, and reversibly — is largely unoccupied.

---

## 4. Future avenues

Roughly in order of payoff:

1. **More codecs.** Geometric progressions; periodic/seasonal patterns (a Fourier or repeating-cycle codec for timestamps and metrics); run-length and dictionary encoding for low-cardinality string columns like `level` or `region`.
2. **Cross-column structure.** Columns are folded independently today. Many tool outputs contain columns that are *functions of other columns* (`count = f(t)`, or one field derivable from another). Detecting and storing only the relationship is a second large win.
3. **Symbolic regression.** Go beyond polynomials — fit `exp`, `log`, `trig`, or piecewise/segmented closed forms automatically, so more columns collapse to a formula.
4. **Predict-and-correct.** Store a cheap model of a column plus only the residuals where it's wrong. This is the bridge toward the LLMLingua world while staying lossless.
5. **Legibility tooling.** A one-time system primer that teaches the model the codec grammar, or "rehydrate on demand" so a column is expanded only when a question actually needs it.

---

## 5. The underlying math — where the fertile ground is

Three fields are already in play, and naming them shows where to dig:

- **Calculus of finite differences** — the engine behind `AFFINE` and `POLY`. Newton's forward-difference formula is exactly how you recover a polynomial from its values. This is the richest near-term vein: the whole classical theory of difference equations and integer sequences (the OEIS world) is a catalog of patterns waiting to become codecs.
- **Number theory, via continued fractions** — powers `RATIONAL`. The Stern–Brocot / convergents machinery finds `355/113` hiding inside `3.14159…`, and generalizes to families of rationals and algebraic constants. This is the Ramanujan thread.
- **Algorithmic information theory — Kolmogorov complexity and its practical proxy, the Minimum Description Length (MDL) principle.** This is the *unifying* field: it tells you whether a new codec is worth adding. Frame the whole project as "find the shortest program that regenerates this data exactly." Every codec is a candidate program; MDL is the judge that picks the shortest. Living in that frame is what keeps the work principled rather than a bag of tricks — because *any* regularity in tool output, not just arithmetic ones, becomes fair game for a new short-description codec.

---

## References

- Prompt Compression for Large Language Models: A Survey (NAACL 2025) — https://arxiv.org/html/2410.12388v2
- LLMLingua (Microsoft Research) — https://www.microsoft.com/en-us/research/blog/llmlingua-innovating-llm-efficiency-with-prompt-compression/
- LLMLingua-2 — https://arxiv.org/pdf/2403.12968
- Lossless Token Sequence Compression via Meta-Tokens — https://arxiv.org/pdf/2506.00307

*Reproduce the legibility numbers:* `python columnar_fidelity.py --live --models "gemini-2.5-flash,gemini-2.5-pro" --repeats 8`

