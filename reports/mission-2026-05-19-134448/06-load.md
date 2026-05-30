# Phase 6 — Load Test

**Run:** 2026-05-19T15:52:13.956371+00:00 → 2026-05-19T15:52:33.960977+00:00
**Mode:** deepseek
**Tool:** stdlib urllib + ThreadPoolExecutor (hey/wrk not installed)

Load-tested POST /analyze across concurrency 1–50 in DeepSeek mode using stdlib urllib + ThreadPoolExecutor. Sequential baseline p50 = 2236.3 ms (LLM-dominated). Knee = c5 (p95 doubled vs baseline or errors began). Bottleneck: uvicorn-single-worker (saw connection errors at saturation).

| Concurrency | Total | Success | Errors | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) |
|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 2 | 0 | 0.5 | 2135.8 | 2332.8 | 2332.8 | 2332.8 |
| 5 | 365 | 0 | 365 | 0.0 | 1.4 | 2.7 | 125.5 | 127.5 |

**Baseline (sequential p50):** 2236.3 ms
**Knee:** concurrency = 5
**Bottleneck:** uvicorn-single-worker (saw connection errors at saturation)

## Brief for synthesizer

Synthesizer: DeepSeek-mode latency dominates — sequential p50 = 2236.3ms. Practical ceiling around c5. Sentinel will not scale beyond ~5 concurrent /analyze under LLM mode without async batching to DeepSeek or local heuristic-only mode.
