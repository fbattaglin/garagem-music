# Section-shot conformance

Samples: **29** · failures: 0 · spent: $0.1036

Rates are over every section asked for, including the ones that failed. Conformance and approval are measured **before the repairer runs**: a section the repairer rescued is a section the model got wrong.

Measured over **29 of 30** briefings drawn (97% askable). The rest fell under `MIN_DEADLINE_S` and were played by the deterministic engine, which is P2 and costs nothing — but they are the hardest sections, so a rate that does not name this number is a rate with a hidden denominator.

| criterion | measured | target | met |
|---|---|---|---|
| schema conformance, first pass | 93% | >= 95% | no |
| validator approval, no repair | 93% | >= 80% | **yes** |
| p95 latency / section deadline | 84% | <= 100% | **yes** |

Reached the buffer at all (repaired or not): 100% — this is the number P2 actually rests on.

## Latency, as a fraction of each section's own deadline

p50 0.56x · p95 0.84x · max 0.84x · over deadline: 0/29

Nearest-rank percentiles over the successful calls, never interpolated. A fraction rather than seconds, because a 4-bar section at 180 BPM has half the budget of an 8-bar one at 132.

## What the model got wrong

| rule | times |
|---|---|
| `schema` | 2 |

A rule that dominates this table is usually a prompt that never stated it. Fix the prompt, not the parser.
