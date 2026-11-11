# ADR-030 — The studio

Status: **accepted** · Date: 2026-11-11 · Planned with Fabiano on 2026-11-10 and corrected by
him the same day. Opens Phase 9. Depends on ADR-024, ADR-025, ADR-026 and ADR-028.

## Context

V1 has a stage and no studio. During a song a person conducts the band from pads, knobs and
typed words, with a screen that says where each cue lands (ADR-028). Everything before the
song is files and scripts:

- a concert is a hand-written `setlists/<name>.toml` whose songs are a title, a key, a feel, a
  tempo and a seed, and nothing else;
- the bake refuses to run if its output exists, so changing one song means paying for all of
  them, and the only partial mode re-asks vetoed sections through the frozen live prompt;
- there is no way to say what kind of song is wanted. The songwriter's prompt says *"The band
  is a rock band"* and the references Fabiano gave live in comments.

A review on 2026-11-10 measured what that costs. In `setlists/show.json`, 99 of 192 drum bars
use the kick written in the prompt's example and 134 of 192 guitar bars use its rhythm, in all
four feels. "Low Ceiling" was baked with no material, because one line of its theme did not
parse and nothing asked again.

The first plan put to Fabiano treated preparation as a set of commands. He rejected it:
*"Temos que poder controlar quando ele compoe, que tipo de musica, gestao do concerto, ordem,
aprovar e rejeitar musicas e outros comando uteis. Imagino duas 'telas' separadas: preparacao
do show e execucao."* He also chose the songwriter's model, `claude-opus-5-5`, and added a
sixth style to the five proposed.

## Decision

**1. Two screens.** `garagem show` plays the concert, as before. `garagem studio` prepares it:
one table of the concert's songs and a line to type on. From it a person says what kind of
song, when it is written, which songs play and in what order.

**2. The files stay the truth.** The studio keeps no state of its own. It reads and writes
the concert's `.toml` and its `.json`, which the bake and the show already read. `SongSpec`
gains `style`, `notes`, `verdict` and `parked`. A file written by the studio can still be
edited by hand; its opening comment is kept and comments inside it are not.

**3. A song has a state, and the show obeys it.** A song is an idea, then composed, then
approved or rejected; it is *changed* when what was asked no longer matches what was written,
and *aside* when it is parked. **The show plays the concert's order and only approved songs**
(`setlist.lineup`). A concert nobody has judged yet plays everything written, so every setlist
from before the studio plays as it did. A song can be heard before it is approved: that is an
audition, and it is the only way to play a song the show would not.

**4. The songwriter never writes by itself.** `compose` and `redo` say what they will cost
and wait for `yes`; anything else typed leaves them undone. A sitting in the studio has its
own cap in `config/budget.toml`, enforced by the governor every model call already goes
through. `--fake` has the players answer in the songwriter's place, into a file of its own.

**5. A song is the unit that is written and paid for.** `compose N` writes one song.
`redo N chorus "heavier"` asks again for one kind of section of it, with the song's own
material and the note in the question. Nothing else is paid for, and what is replaced is kept
with the song, as a vetoed take is.

**6. A style is one object, read by whoever needs it.** A file per style in `styles/`: a
direction in words, and a palette of feels, scales and tempos. Today the songwriter and the
studio read it. Six styles: `arena`, `desert`, `interlock`, `riff-stops`, `duo`, `southern`. A
style is described by what the band does, never by a song; the bands a person would think of
are named for the person and not sent to the model.

**7. The songwriter is told more, all of it in the message.** The style's direction and the
bandleader's notes; where the section sits in the song, which nothing told it before; and that
the example in its instructions belongs to another song. The cached system block does not
move.

**8. The material is asked for twice, like a section.** A theme the parser refuses is asked
for once more before the song is written without one.

**9. The songwriter's model is configuration.** `config/models.toml` marks one model with
`role = "composer"`. It is `claude-opus-5-5`. That model rejects a forced tool choice, so a
model may declare `forced_tool = false`: the tool is offered, the prompt names it, and an
answer in prose is a failed call like any other. The live layers stay on the models their
deadlines were measured with (ADR-025).

**10. The songwriter is an agent with a module.** The bake's core moves from
`scripts/bake_setlist.py` to `agents/songwriter.py`, because a screen cannot call a script.
The script is a wrapper over it.

## Rejected alternatives

- **Commands only, no screen.** The first plan. Rejected by Fabiano: preparing a show is a
  place, not a list of scripts to remember.
- **The studio's own state file.** Two truths about one concert, and the hand-edited `.toml`
  would stop being one of them.
- **A dependency to write TOML.** The format is a name and flat tables of text, numbers and
  a switch. Forty lines write it, and the project stays lean.
- **A content-addressed cache of takes.** What it would save is already saved by composing
  one song at a time and comparing what was asked with what was written (`composed_as`). A
  changed style or note changes every question of the song, so there is nothing to reuse
  there.
- **Sending the reference bands to the model.** A band's name asks for its songs. The
  direction asks for what a band does, which is what the notation can carry.
- **A software amplifier for the guitars.** Raised for the phase after this one, and ruled
  out by Fabiano on 2026-11-11: nothing is installed beyond what the band already uses. The
  sound is improved with what Live Lite has.
- **Moving the live layers to the new model too.** Live generation is frozen (ADR-025) and
  its deadlines were measured against the models it uses.

## Consequences

- **A style changes what is written and not how it sounds.** The players play every style
  with the same hands and the same sounds. `duo` cannot yet silence the bass. Styles reaching
  the players, the form and the sound are later phases.
- **When this was written nothing had been heard or paid for.** Every test runs against the
  players answering as the songwriter. The usage the estimate rested on was measured with the
  previous model, so the first paid `compose` was the measurement: `phase-9-findings.md` §5
  has it, and the verdict.
- **The songwriter's prompts are still not pinned by cassettes.** Recording them costs money
  and waits on the same bake.
- **A redo of a vetoed take now asks with the song's material.** Before, the replacement came
  through the live prompt, with no theme, no pitches and no lead.
- **What the model writes is still partly thrown away.** Its organ chords are realised as
  short stabs, and its last bar and crashes are overwritten by the form. Both change the notes
  of every baked take and need a listen, so they are not in this phase.
- **The whole setlist in one run is still not built** (ADR-028 §7). The show plays one song
  per command, now in the concert's order.
