"""Benchmark: Ramanujan LSH vs brute-force cosine search.

Measures recall, index time, and query time at various scales.
Run: python benchmarks/bench_ramanujan_vs_bruteforce.py
"""

from __future__ import annotations

import time

import numpy as np

from headroom.memory.backends.ramanujan_lsh import RamanujanLSH


def _brute_force_search(
    query: np.ndarray,
    vectors: dict[str, np.ndarray],
    k: int,
) -> list[tuple[str, float]]:
    """Exact cosine nearest neighbors (ground truth)."""
    results = []
    for mid, vec in vectors.items():
        sim = float(np.dot(query, vec))
        results.append((mid, 1.0 - sim))  # cosine distance
    results.sort(key=lambda x: x[1])
    return results[:k]


def run_benchmark(
    n_vectors: int,
    dimension: int,
    num_tables: int,
    hash_bits: int,
    n_queries: int = 100,
    k: int = 10,
) -> dict:
    rng = np.random.RandomState(42)

    # Generate random unit vectors
    raw = rng.randn(n_vectors, dimension).astype(np.float32)
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    raw = raw / norms

    vectors = {f"v{i}": raw[i] for i in range(n_vectors)}

    # Index into LSH
    lsh = RamanujanLSH(
        dimension=dimension,
        num_tables=num_tables,
        hash_bits=hash_bits,
        seed=42,
    )

    t0 = time.perf_counter()
    for mid, vec in vectors.items():
        lsh.add(mid, vec)
    index_time = time.perf_counter() - t0

    # Generate queries (use existing vectors for reproducible recall)
    query_ids = [f"v{i}" for i in rng.choice(n_vectors, n_queries, replace=False)]

    # LSH queries
    lsh_times = []
    lsh_results = {}
    for qid in query_ids:
        q = vectors[qid]
        t0 = time.perf_counter()
        results = lsh.query(q, k=k)
        lsh_times.append(time.perf_counter() - t0)
        lsh_results[qid] = {r.memory_id for r in results}

    # Brute-force queries (ground truth)
    bf_times = []
    bf_results = {}
    for qid in query_ids:
        q = vectors[qid]
        t0 = time.perf_counter()
        results = _brute_force_search(q, vectors, k=k)
        bf_times.append(time.perf_counter() - t0)
        bf_results[qid] = {mid for mid, _ in results}

    # Compute recall@k
    recalls = []
    for qid in query_ids:
        lsh_set = lsh_results[qid]
        bf_set = bf_results[qid]
        recall = len(lsh_set & bf_set) / len(bf_set) if bf_set else 1.0
        recalls.append(recall)

    # Self-recall: does LSH find the query vector itself?
    self_recalls = []
    for qid in query_ids:
        self_recalls.append(1.0 if qid in lsh_results[qid] else 0.0)

    return {
        "n_vectors": n_vectors,
        "dimension": dimension,
        "num_tables": num_tables,
        "hash_bits": hash_bits,
        "index_time_ms": index_time * 1000,
        "index_per_vec_us": index_time / n_vectors * 1e6,
        "lsh_query_ms_median": np.median(lsh_times) * 1000,
        "lsh_query_ms_p95": np.percentile(lsh_times, 95) * 1000,
        "bf_query_ms_median": np.median(bf_times) * 1000,
        "bf_query_ms_p95": np.percentile(bf_times, 95) * 1000,
        "speedup_median": np.median(bf_times) / np.median(lsh_times) if np.median(lsh_times) > 0 else float("inf"),
        "recall_at_k_mean": np.mean(recalls),
        "recall_at_k_min": np.min(recalls),
        "self_recall": np.mean(self_recalls),
    }


def main() -> None:
    configs = [
        {"n_vectors": 1000, "dimension": 128, "num_tables": 12, "hash_bits": 8},
        {"n_vectors": 1000, "dimension": 384, "num_tables": 16, "hash_bits": 8},
        {"n_vectors": 5000, "dimension": 128, "num_tables": 12, "hash_bits": 8},
        {"n_vectors": 5000, "dimension": 384, "num_tables": 16, "hash_bits": 8},
        {"n_vectors": 10000, "dimension": 384, "num_tables": 20, "hash_bits": 10},
    ]

    print(f"{'N':>7} {'dim':>5} {'tables':>7} {'bits':>5} "
          f"{'idx ms':>8} {'LSH ms':>8} {'BF ms':>8} {'speedup':>8} "
          f"{'recall':>8} {'self':>6}")
    print("-" * 90)

    for cfg in configs:
        r = run_benchmark(**cfg)
        print(
            f"{r['n_vectors']:>7} {r['dimension']:>5} {r['num_tables']:>7} {r['hash_bits']:>5} "
            f"{r['index_time_ms']:>7.1f} {r['lsh_query_ms_median']:>7.3f} "
            f"{r['bf_query_ms_median']:>7.3f} {r['speedup_median']:>7.1f}x "
            f"{r['recall_at_k_mean']:>7.1%} {r['self_recall']:>5.0%}"
        )

    print()
    print("recall = fraction of brute-force top-10 found by LSH")
    print("self   = fraction of queries where LSH finds the query vector itself")
    print("speedup = brute-force median / LSH median query time")


if __name__ == "__main__":
    main()
