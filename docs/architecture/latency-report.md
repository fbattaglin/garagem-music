# Latency report - TTFT per model

Samples: **78** - window: 2026-08-30T09:03:15 to 2026-08-30T18:02:37

TTFT in seconds, nearest-rank percentiles over successful calls.

| provider | model | n | fail | p50 | p95 | p99 | max | p99/p50 | tok/s | late@5.8s | $ | times of day |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| anthropic | `claude-opus-5` | 16 | 0 | 1.58 | 6.11 | 6.11 | 6.11 | 3.9x | 118 | 1/16 | 0.1320 | 3/3 yes |
| anthropic | `claude-sonnet-5` | 16 | 0 | 1.42 | 1.52 | 1.52 | 1.52 | 1.1x | 81 | 0/16 | 0.0878 | 3/3 yes |
| google | `gemini-flash-lite-latest` | 16 | 2 | 0.92 | 31.98 | 31.98 | 31.98 | 34.6x | 79885 | 2/14 | 0.0048 | 3/3 yes |
| anthropic | `claude-haiku-4-5-20251001` | 15 | 0 | 1.08 | 14.38 | 14.38 | 14.38 | 13.3x | 284 | 2/15 | 0.0304 | 3/3 yes |
| google | `gemini-3.6-flash` | 15 | 6 | 12.31 | 47.82 | 47.82 | 47.82 | 3.9x | 69444 | 9/9 | 0.0915 | 3/3 yes |

## Reading this

- `claude-opus-5`: n=16 < 100, so p99 is the maximum observed, not an estimate of the tail. Read `max`, and treat p95 as the honest tail.
- `claude-opus-5`: 1/16 calls (6%) came back after 5.8 s. A real section-shot would have cancelled those and played the deterministic part instead.
- `claude-sonnet-5`: n=16 < 100, so p99 is the maximum observed, not an estimate of the tail. Read `max`, and treat p95 as the honest tail.
- `gemini-flash-lite-latest`: n=16 < 100, so p99 is the maximum observed, not an estimate of the tail. Read `max`, and treat p95 as the honest tail.
- `gemini-flash-lite-latest`: 2/14 calls (14%) came back after 5.8 s. A real section-shot would have cancelled those and played the deterministic part instead.
- `gemini-flash-lite-latest`: tail ratio 34.6x is above the 2-5x that section 4.2 predicts. The 2-section lookahead was sized on that assumption.
- `claude-haiku-4-5-20251001`: n=15 < 100, so p99 is the maximum observed, not an estimate of the tail. Read `max`, and treat p95 as the honest tail.
- `claude-haiku-4-5-20251001`: 2/15 calls (13%) came back after 5.8 s. A real section-shot would have cancelled those and played the deterministic part instead.
- `claude-haiku-4-5-20251001`: tail ratio 13.3x is above the 2-5x that section 4.2 predicts. The 2-section lookahead was sized on that assumption.
- `gemini-3.6-flash`: n=15 < 100, so p99 is the maximum observed, not an estimate of the tail. Read `max`, and treat p95 as the honest tail.
- `gemini-3.6-flash`: 9/9 calls (100%) came back after 5.8 s. A real section-shot would have cancelled those and played the deterministic part instead.
