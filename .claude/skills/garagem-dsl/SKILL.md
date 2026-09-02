---
name: garagem-dsl
description: Specification of the GARAGEM symbolic DSL (SEC, CHD, DRM, BAS, GTR, KEY) and of the tool-use schema used to generate musical sections. Use when writing or changing the parser, serializer, agent prompts or validators, or when interpreting model output.
---

# GARAGEM/0.1 DSL

A compact symbolic representation exchanged between agents and expanded into MIDI by
deterministic code. Optimised for few tokens and for the model to "see" the rhythmic
grid.

## Section level

```
SEC verse bars=8 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4
CHD | Em | Em | C  | D  | Em | Em | C  | B7 |
```

- `feel`: `straight8` | `straight16` | `shuffle` | `halftime`
- `dyn`: 1–5 (arrangement dynamics)
- `tension`: 0.0–1.0 (feeds density and harmonic risk)

## Bar level

```
DRM K:x..x..x...x..x.. S:....x.......x... H:x.x.x.x.x.x.x.x. C:x...............
BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x. ghost=7,15
GTR voi=pow rhy:xx.xxx.xxx.xx.x. palm=on acc=1,9
KEY voi=sus2 rhy:x.......x....... reg=mid
```

- 16-sixteenth grid. `x` = attack, `.` = rest.
- `K`/`S`/`H`/`C` = kick, snare, hi-hat, crash.
- `deg` = scale degree (1–7) relative to the current chord, not an absolute note.
- `acc` = accented positions (1-indexed within the grid).

## Emission order — mandatory

`SEC` -> `CHD` -> `DRM` -> `BAS` -> `GTR` -> `KEY`

The order follows rhythmic priority and exists to allow **incremental parsing**: drums
and bass arrive first and can already be written into the clip while the rest is still
being generated. Never reorder it.

## Invariants the validator enforces

- Every `BAS` note falls within E1–G3; `GTR` within E2–E5; `KEY` within C2–C6.
- Bass degree 1 on beat 1 of each chord, unless `tension > 0.7`.
- No open and closed hi-hat in the same slot.
- Minimum interval between consecutive kicks: 60 ms, unless `double_kick=on`.
- Notes outside the current chord/scale are limited by the section's dissonance budget.

Invalid output is repaired deterministically. If irreparable, it falls back to the
deterministic engine and the event is logged — a bar is never discarded.

## Anti-patterns

- Do not ask the model for raw MIDI in JSON: ~14x more tokens and no musical gain.
- Do not use a hex encoding of the grid: cheap in tokens, but the model reasons poorly
  about bits.
- Do not instruct the format in the prompt and parse free text. Use tool use with a
  strict schema and keep the prompt focused on musical intent.
