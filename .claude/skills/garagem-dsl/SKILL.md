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

## The bake's superset — read, and written only when asked

Since ADR-026 the notation has **two vocabularies, and the frozen half is the one with
cassettes against it.** GARAGEM/0.1 is what the live prompt teaches and what
`serialize_section` writes by default: the four voices above, `BAS deg=` naming one degree
for a whole bar, and no lead. The parser reads more than that, and `serialize_section(...,
pitched=True)` writes it — for the offline bake, where there is no 5.8 s deadline and the
model can be asked for pitches.

    BAS oct=2 deg:1=1,5=5,9=7,13=1     a degree per struck slot: the line moves in the bar
    LED oct=4 deg:9=5,11=3,13=1 hold=13    the fifth voice; hold= rings to the next attack
    LED oct=4 deg:                     a bar the lead sits out, which is most of them

- Slots are 1-indexed, like every other position in this notation. **The struck slots are
  the keys**: `deg:` carries the rhythm and the pitch together, so there is no `rhy:`
  beside it — writing both is refused.
- `deg=` and `deg:` are different line forms, told apart by the separator. A lead has no
  `deg=` form: `LED ... deg=5` is refused by name.
- Degrees are 1..7 of the *bar's chord*. A slot outside 1..16, a degree outside 1..7, a
  pair that is not `slot=degree`, and a slot given two degrees are each refused by name.
- **Truncation is measured against the four**, not the five: a section whose lead rests
  has no `LED` line, and that is complete, not cut off.
- `LEAD` is last in the emission order, so nothing written before ADR-026 moves.

## Invariants the validator enforces

- Every `BAS` note falls within E1–G3; `GTR` within E2–E5; `KEY` within C2–C6; `LED`
  within G3–C6.
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
