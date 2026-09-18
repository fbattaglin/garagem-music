# Phase 6 findings

## 1. The shuffle gets its own vocabulary

Built on 2026-09-17, with no model and no network. It is Stage A of
[ADR-026](ADR-026-the-songwriter.md), and the reason is Phase 5's closing verdict: *"A musica
número dois … foi sem dúvidas a menos interessante e mais mecanica delas"*
(`phase-5-findings.md` §13).

### What was wrong, in sound

Under a shuffle the whole band landed on the same eight attacks. The hats played the swung
eighths at every dynamic, the bass pulsed those same eighths, the guitar strummed them, and
straightening puts a model's take on them too. Nothing was left for anything to answer.

### What each player does now

| | Before | Now |
|---|---|---|
| Bass (`engines/bass.py`) | eighths | **the beats**, `x...x...x...x...` |
| Guitar (`engines/guitar.py`) | eighths | **the swung offbeats**, `..x...x...x...x.` |
| Keys, stabbing (`engines/keys.py`) | quarters | **the backbeat**, with the snare |
| Drums (`engines/groove.py`) | unchanged | unchanged, except the loudest kick |

**In sound:** the bass walks on the beat, the guitar chops the late half of each beat, the keys
punch with the snare, and the hats keep both halves. Four players, four places.

**The loudest shuffle's kick moved onto the swung eighths.** It was `1,4,7,9,12,15` — two kicks
a bar *between* them, the same three-by-three push the model wrote on its hat and that
straightening exists to remove (`phase-5-findings.md` §2). It is now `1,3,7,9,11,15`. That was
the one place the floor contradicted its own shuffle, and nobody is known to have heard it: no
A/B pair reached dyn 5.

### What did not move

- Fills, stops, builds and the final chord: feel-independent, and approved by ear.
- Every other feel. `straight8`, `straight16` and `halftime` are untouched, and the property
  tests over them are unchanged.
- The bass's tension behaviour: the fifth still arrives above 0.35 and the walk above 0.65. Four
  attacks a bar is exactly `WALKING_MIN_ATTACKS`, so a high-tension shuffle still walks into the
  next chord.

### What it cost to check

- Two golden files regenerated, `verse-shuffle-7.dsl` and `verse-shuffle-1729.dsl`, and the diff
  read before it was kept: the bass drops from 32 notes to 16, the guitar moves onto the
  offbeats, and the drums are identical.
- `test_dsl_straighten.py` says the new truth: **the floor's shuffle is now a fixed point of
  straightening at every dynamic**, flat out included. That test used to carry the exception.
- Suite: **2243 passed, 27 skipped**; `ruff` and `mypy` clean.

### Heard

One shuffle jam, `jam.py --seconds 120 --feel shuffle --seed 11`, on 2026-09-17. Fabiano:

> *"Achei que teve muito mais alma. Muito bom."*

That closes the gate ADR-025 asks for: approved music was changed on the strength of one verdict,
and the change was heard before anything was built on top of it. **The floor's shuffle is
approved as it now stands**, and it is Phase 6's criterion 2.

Worth keeping beside the verdict: the bass went from eight attacks a bar to four, which was the
risk in the change, and nothing came back as thin.
