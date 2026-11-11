# Phase 9 findings

## 1. The studio (ADR-030)

**What was asked for.** Fabiano, 2026-11-10, rejecting a first plan made of commands: *"Temos
que poder controlar quando ele compoe, que tipo de musica, gestao do concerto, ordem, aprovar e
rejeitar musicas e outros comando uteis. Imagino duas 'telas' separadas: preparacao do show e
execucao."*

**What was built.** `garagem studio`: one table of the concert's songs and a line to type on.

| To decide | Typed |
|---|---|
| what kind of song | `new <style>`, `style`, `key`, `tempo`, `feel`, `length`, `note`, `title`, `seed` |
| when the songwriter writes | `compose N`, `compose all`, `redo N`, `redo N chorus "heavier"`, then `yes` |
| which songs play | `listen N`, `approve N`, `reject N` |
| the concert | `move`, `drop`, `add`, `delete`, `undo`, `concert new`, `concert open` |
| looking | `sheet N`, `styles`, `cost`, `check`, `show`, `help` |

The show now plays the concert's order and only approved songs, once any song has been judged.
A setlist from before the studio has no verdicts and plays as it did.

**Six styles** in `styles/`: `arena`, `desert`, `interlock`, `riff-stops`, `duo`, `southern`.
Each is a direction in words and a palette. `southern` was added by Fabiano on 2026-11-11.

**The songwriter is `claude-opus-5-5`**, chosen by Fabiano, marked in `config/models.toml`.

## 2. Found on the way

- **The new model would have refused every call.** Opus 5.5 answers a forced `tool_choice`
  with a 400, and the adapter forced it on every request. Found by reading the model's
  documentation before the first call, not by paying for one. A model now declares whether it
  can be forced.
- **A second field on `Request` would have broken every cassette.** A cassette matches a
  fingerprint of the whole request. The new field is left out of the dump, so the 29 recorded
  sections still replay.
- **`arrangement.json` is a setlist called `songwriter`.** Phase 7's naming accident
  (`phase-7-findings.md` §6) is still in the file; a test written against the file's name
  found it. Left as it is: its curation is keyed by that name.
- **The material's cost is not stored.** A take records what it cost; the call that wrote a
  song's material records nothing, so `cost` in the studio says so rather than adding up to
  less than was spent.

## 3. Measured

- Suite at **3500 passed, 27 skipped** (3394 at V1), `ruff` and `mypy --strict` clean.
- The studio is tested by typed lines against a copy of a concert: 37 tests, among them that
  nothing is sent before `yes`, that the free bake never touches the paid one's file, and that
  asking again for a chorus pays for the choruses and leaves every other take as it was.
- Every concert in `setlists/` survives being written back by the studio.
- **The estimate for the show's four songs with the new model is about $0.69**, against
  $0.3964 spent on them with the previous one. It rests on token counts measured with the
  previous model.

## 4. What was open before the first paid song

Written before anything was paid for or heard, and answered in §5:

1. Whether Opus 5.5 answers through the tool when it is offered and not forced.
2. What a song costs with it, against the estimate above.
3. Whether a style can be heard: one song written in two styles, told apart without looking.
4. Whether the model still copies the example's kick and guitar rhythm: 99 and 134 of 192
   bars in the show's bake.

## 5. Used, paid for and heard (2026-11-11)

Fabiano prepared the concert in the studio: three songs sketched from styles, two of them
titled by him ("Smoking and Driving", `desert`; "Our Love is a Rat Race", `riff-stops`; one
`arena` song still untitled), each composed, five listens, one song approved
(`bench/studio.jsonl`).

**His verdict:** *"Tudo que compus e escutei até agora achei muito bom. Um salto comparado com
V1."*

**The new songwriter answers.** 19 of 19 sections delivered and 3 of 3 themes, none asked
twice, through a tool it was offered and not forced onto.

**The estimate was wrong, by more than half.** The studio said *about $0.17* for the `arena`
song and it cost $0.40; the three songs cost $1.55 together, $1.44 of it in sections. Each
stayed under the "at most" figure and the sitting's $2.00 cap held, but the expected figure
is the one a person decides on. It rested on token counts from the previous model: 1286 out a
section, against a median of 3300 with this one, which thinks before it writes. The constants
now carry the 19 sections measured here. The largest answer was 5982 tokens of the 8192
allowed.

**It mostly stopped copying the example.** Bars using the prompt example's kick: 3 of 152,
against 99 of 192 in the show's first bake. Its guitar rhythm: 18 of 152, against 134 of 192.
The model, the sentence about the example and the style's direction all changed together, so
this does not say which of them did it.

**Not answered:** whether a style can be heard. Three songs in three styles were written and
liked; no song was written twice in two styles and told apart blind. The four songs of V1 are
still as they were, "Low Ceiling" without its material.
