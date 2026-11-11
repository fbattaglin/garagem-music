"""`garagem studio`: the room where the show is prepared (ADR-030).

The stage has had its screen since ADR-028. Everything before the stage was files edited by
hand and scripts run in the right order. This is the other screen: one table of the concert's
songs and a line to type on, and from it a person decides

- **what kind of song**: `new <style>`, then `style`, `key`, `tempo`, `feel`, `note`;
- **when the songwriter writes**, and so when money is spent: `compose`, `redo`, each one
  answered with what it will cost and done only after `yes`;
- **what the concert is**: `move`, `drop`, `add`, `delete`, `concert`;
- **which songs play**: `listen`, then `approve` or `reject`.

**The files stay the truth.** The studio keeps nothing of its own: it reads and writes the
concert's `.toml` (what was asked) and its `.json` (what was written), which is what the bake
and the show already read. A concert edited here can still be edited by hand.

**It never spends by itself.** A paid command says its estimate and waits for `yes`; anything
else typed instead leaves it undone. The session has a cap (`config/budget.toml`), enforced by
the same governor every model call goes through.

**`--fake` is the whole studio for free.** The players answer in the songwriter's place, into
`<name>.fake.json`, so the screen can be learned and rehearsed without a key or a cent, and
the real bake's file is never touched by it.

Like the show's typed words (ADR-028), a line is matched whole: an unknown word is said back
as unknown and changes nothing.
"""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final, TextIO

from pydantic import ValidationError

from garagem.agents import composer, worth_asking
from garagem.agents.songwriter import (
    Planned,
    compose_song,
    estimate,
    floor_answers,
    floor_sections,
    guarded,
    plan_song,
    planned_from,
    redo,
)
from garagem.daw import load_session
from garagem.domain import Feel
from garagem.llm import (
    BakedProvider,
    GuardedProvider,
    LLMProvider,
    ModelSpec,
    ProviderError,
    Warmable,
    load_catalog,
    load_studio_cap,
)
from garagem.obs import EventLog
from garagem.setlist import (
    Setlist,
    SetlistError,
    SetlistSpec,
    Song,
    SongSpec,
    Style,
    TakeStatus,
    Verdict,
    askable,
    composed_as,
    direction_for,
    lineup,
    load_setlist,
    load_spec,
    load_styles,
    save_setlist,
    save_spec,
    sketch,
)
from garagem.theory import render_key

NOTES: Final = {
    "c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "f": 5, "f#": 6, "gb": 6,
    "g": 7, "g#": 8, "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11,
}  # fmt: skip
SCALES: Final = ("major", "minor")

# Every word the studio knows, in the order `help` prints them.
WORDS: Final[tuple[tuple[str, str], ...]] = (
    ('new <style> ["notes"]', "a new song in a style; `styles` lists them"),
    ('title N "name"', "name a song"),
    ("style N <style>", "change its style: a name from `styles`, or your own words in quotes"),
    ("key N <note> [major|minor]", "change its key: key 2 D minor"),
    ("tempo N <bpm>", "change its tempo"),
    ("feel N <feel>", "straight8, straight16, shuffle or halftime"),
    ("length N <seconds>", "how long the song should be, at least"),
    ('note N "words"', 'tell the songwriter something about this song; "" clears it'),
    ("seed N <number>", "another arrangement of the same song: a different form"),
    ("compose N | all", "have the songwriter write a song, or every song not written yet"),
    ("redo N", "write the whole song again"),
    ('redo N <section> ["note"]', 'write one kind of section again: redo 2 chorus "heavier"'),
    ("yes", "go ahead with what was just estimated"),
    ("listen N", "play a song with the band (needs Live); keeps and vetoes are saved after"),
    ("approve N / reject N", "say whether a song plays in the show"),
    ("move N M", "put song N at position M"),
    ("drop N / add N", "set a song aside, out of the concert, or bring it back"),
    ("delete N", "take a song out of the concert's file"),
    ("sheet N", "a song in words: its form, who wrote what, what it cost"),
    ('concert [new|open "name"]', "list the concerts, start one, or open another"),
    ("styles", "the styles a song can be written in"),
    ("cost", "what this session has spent, and what the concert cost to write"),
    ("check", "whether the show can start"),
    ("show", "which songs the show will play, and the command that plays them"),
    ("undo", "take back the last change to the concert"),
    ("help", "this list"),
    ("quit", "leave the studio"),
)


class StudioError(ValueError):
    """Something typed that the studio will not do. The message is what it says back."""


@dataclass(frozen=True, slots=True)
class StudioFiles:
    concert: Path
    styles: Path
    session: Path
    catalog: Path
    budget: Path
    log: Path


@dataclass(frozen=True, slots=True)
class StudioWiring:
    """How the studio reaches the songwriter and the stage. Swapped for fakes in tests."""

    # The paid songwriter. Raises `ProviderError` when there is no key.
    connect: Callable[[], LLMProvider]
    # Plays one song of this bake by title and says how it went. None: no stage here.
    listen: Callable[[Path, str], str] | None = None
    # The ready check against this bake, rendered. None: no stage here.
    check: Callable[[Path], str] | None = None
    today: Callable[[], date] = date.today


def bake_of(concert: Path, *, fake: bool) -> Path:
    """Where a concert's songs are written: beside it, and apart when the players wrote them."""
    return concert.with_suffix(".fake.json" if fake else ".json")


def clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


class Studio:
    """The concert being prepared, and what each typed line does to it."""

    def __init__(self, files: StudioFiles, wiring: StudioWiring, *, fake: bool = False) -> None:
        self._files = files
        self._wiring = wiring
        self._fake = fake
        self._catalog = load_catalog(files.catalog)
        self._model: ModelSpec = composer(self._catalog)
        self._cap = load_studio_cap(files.budget)
        self._set_bpm = load_session(files.session).tempo_bpm
        self._styles: dict[str, Style] = load_styles(files.styles)
        self._log = EventLog(files.log)
        self._spent = Decimal(0)
        self._undo: list[list[SongSpec]] = []
        self._pending: Callable[[], str] | None = None
        self.done = False
        self._concert = files.concert
        self._songs: list[SongSpec] = []
        self._setlist: Setlist | None = None
        self._open(files.concert)

    # ------------------------------------------------------------------- the files

    def _open(self, concert: Path) -> None:
        songs = list(load_spec(concert).songs) if concert.exists() else []
        bake = bake_of(concert, fake=self._fake)
        setlist = load_setlist(bake) if bake.exists() else None
        self._concert, self._songs, self._setlist = concert, songs, setlist
        self._undo, self._pending = [], None

    @property
    def name(self) -> str:
        return self._concert.stem

    @property
    def bake(self) -> Path:
        return bake_of(self._concert, fake=self._fake)

    def _baked(self, title: str) -> Song | None:
        songs = self._setlist.songs if self._setlist is not None else ()
        return next((song for song in songs if song.title == title), None)

    def _commit(self, songs: list[SongSpec], *, undoable: bool = True) -> None:
        """Make `songs` the concert, on disk first: a concert the file refuses is not kept."""
        if not songs:
            raise StudioError("a concert keeps at least one song; `drop` sets one aside instead")
        try:
            spec = SetlistSpec(name=self.name, songs=tuple(songs))
        except ValidationError as exc:
            raise StudioError(str(exc.errors()[0]["msg"])) from exc
        save_spec(spec, self._concert)
        if undoable:
            self._undo.append(self._songs)
        self._songs = songs

    def _store(self, song: Song) -> None:
        """Put a written song into the bake, in the place it had or at the end."""
        old = self._baked(song.title)
        if old is not None:
            # What it replaces is kept with it, as a vetoed take is: evidence, not rubbish.
            song = song.model_copy(update={"retired": (*old.retired, *old.takes)})
        songs = list(self._setlist.songs) if self._setlist is not None else []
        titles = [each.title for each in songs]
        if song.title in titles:
            songs[titles.index(song.title)] = song
        else:
            songs.append(song)
        self._setlist = Setlist(
            name=self.name,
            provider="fake" if self._fake else "anthropic",
            model=self._model.id,
            baked_on=self._wiring.today(),
            bpm=self._set_bpm,
            songs=tuple(songs),
        )
        save_setlist(self._setlist, self.bake)

    def _record(self, kind: str, **detail: str | int | float | bool) -> None:
        self._log.record(kind, 0.0, concert=self.name, **detail)
        self._log.flush()

    # ------------------------------------------------------------------ the screen

    def state_of(self, asked: SongSpec) -> str:
        """One word for where a song is: idea, composed, changed, approved, rejected, aside."""
        baked = self._baked(asked.title)
        if asked.parked:
            return "aside"
        if asked.verdict is not Verdict.NONE:
            return str(asked.verdict)
        if baked is None:
            return "idea"
        return "composed" if composed_as(asked, baked, self._set_bpm) else "changed"

    def screen(self) -> str:
        playing = self._lineup()
        mode = "  [fake: the players write, free]" if self._fake else ""
        head = (
            f'GARAGEM · STUDIO   concert "{self.name}"   '
            f"{len(self._songs)} songs, {len(playing)} in the show "
            f"({clock(sum(song.total_seconds() for song in playing))})   "
            f"spent ${self._spent:.2f} of ${self._cap:.2f}{mode}"
        )
        rows = [
            " #  song                  style       key  feel        bpm  state     written  notes"
        ]
        for number, asked in enumerate(self._songs, start=1):
            baked = self._baked(asked.title)
            bpm = self._set_bpm if asked.bpm is None else asked.bpm
            rows.append(
                f"{number:>2}  {asked.title[:20]:<20}  {(asked.style or '-')[:10]:<10}  "
                f"{render_key(asked.key, asked.scale):<3}  {asked.feel!s:<10}  {bpm:>3g}  "
                f"{self.state_of(asked):<8}  {self._written(baked):<7}  {asked.notes[:36]}"
            )
        if not self._songs:
            rows.append("    no songs yet: new <style>, and `styles` lists the styles")
        return "\n".join([head, *rows]) + "\n"

    def _written(self, baked: Song | None) -> str:
        if baked is None:
            return "-"
        asked = len(askable(baked.form, worth_asking))
        marks = sum(1 for take in baked.takes if take.status is not TakeStatus.UNMARKED)
        return f"{len(baked.takes)}/{asked}" + (f" {marks}m" if marks else "")

    def _lineup(self) -> tuple[Song, ...]:
        if self._setlist is None or not self._songs:
            return ()
        return lineup(self._setlist, SetlistSpec(name=self.name, songs=tuple(self._songs)))

    # ------------------------------------------------------------------- the words

    def execute(self, line: str) -> str:
        """What one typed line does, and what the studio says back. Never raises."""
        try:
            words = shlex.split(line)
        except ValueError:
            return "a quote was opened and not closed; nothing done"
        if not words:
            return ""
        word, args = words[0].lower(), words[1:]
        pending, self._pending = self._pending, None
        left = ""
        if word == "yes":
            if pending is None:
                return "nothing is waiting for a yes"
            handler: Callable[[list[str]], str] | None = lambda _: pending()  # noqa: E731
        else:
            handler = self._handlers().get(word)
            left = "left undone: it was waiting for yes. " if pending is not None else ""
        if handler is None:
            return f"{words[0]!r}: no such word, type help"
        try:
            return left + handler(args)
        except (StudioError, SetlistError) as exc:
            return left + str(exc)

    def _handlers(self) -> dict[str, Callable[[list[str]], str]]:
        return {
            "new": self._new,
            "title": lambda a: self._edit(a, "title", str, music=False),
            "style": lambda a: self._edit(a, "style", str),
            "note": lambda a: self._edit(a, "notes", str),
            "tempo": lambda a: self._edit(a, "bpm", float),
            "length": lambda a: self._edit(a, "seconds", float),
            "seed": lambda a: self._edit(a, "seed", int),
            "feel": lambda a: self._edit(a, "feel", Feel),
            "key": self._key,
            "compose": self._compose,
            "redo": self._redo,
            "listen": self._listen,
            "approve": lambda a: self._judge(a, Verdict.APPROVED),
            "reject": lambda a: self._judge(a, Verdict.REJECTED),
            "move": self._move,
            "drop": lambda a: self._park(a, True),
            "add": lambda a: self._park(a, False),
            "delete": self._delete,
            "sheet": self._sheet,
            "concert": self._concerts,
            "styles": self._list_styles,
            "cost": self._cost,
            "check": self._check,
            "show": self._show,
            "undo": self._take_back,
            "help": lambda a: "\n".join(f"  {usage:<30} {what}" for usage, what in WORDS),
            "quit": self._quit,
            "no": lambda a: "nothing done",
        }

    def _at(self, args: Sequence[str]) -> int:
        """The song a command names by its number on the screen, as an index."""
        if not args or not args[0].isdigit():
            raise StudioError("which song? give its number on the screen")
        number = int(args[0])
        if not 1 <= number <= len(self._songs):
            raise StudioError(f"song {number}: the concert has songs 1 to {len(self._songs)}")
        return number - 1

    def _replace(self, at: int, changes: dict[str, object]) -> SongSpec:
        try:
            return SongSpec.model_validate({**self._songs[at].model_dump(), **changes})
        except ValidationError as exc:
            raise StudioError(f"{exc.errors()[0]['msg']}; nothing changed") from exc

    # ---------------------------------------------------------- what kind of song

    def _new(self, args: list[str]) -> str:
        if not args or args[0] not in self._styles:
            return 'new <style> ["notes"]. ' + self._list_styles([])
        seed = max((song.seed for song in self._songs), default=0) + 1
        taken = {song.title for song in self._songs}
        title = next(
            f"Untitled {n}" for n in range(1, len(taken) + 2) if f"Untitled {n}" not in taken
        )
        song = sketch(self._styles[args[0]], title, seed, " ".join(args[1:]))
        self._commit([*self._songs, song])
        self._record("song_sketched", title=title, style=song.style, seed=seed)
        bpm = self._set_bpm if song.bpm is None else song.bpm
        return (
            f"{len(self._songs)}. {title}: {song.style}, {render_key(song.key, song.scale)}, "
            f"{song.feel}, {bpm:g} BPM. Change anything, then compose {len(self._songs)}."
        )

    def _edit(self, args: list[str], field: str, kind: type, *, music: bool = True) -> str:
        at = self._at(args)
        if len(args) < 2:
            raise StudioError(f"what should song {at + 1}'s {field} be?")
        try:
            value = kind(" ".join(args[1:]) if kind is str else args[1])
        except ValueError as exc:
            raise StudioError(f"{args[1]!r} is not a {field}; nothing changed") from exc
        return self._change(at, {field: value}, music=music)

    def _key(self, args: list[str]) -> str:
        at = self._at(args)
        if len(args) < 2 or args[1].lower() not in NOTES:
            raise StudioError("key N <note> [major|minor], as in: key 2 D minor")
        changes: dict[str, object] = {"key": NOTES[args[1].lower()]}
        if len(args) > 2:
            if args[2].lower() not in SCALES:
                raise StudioError(f"{args[2]!r}: major or minor")
            changes["scale"] = args[2].lower()
        return self._change(at, changes)

    def _change(self, at: int, changes: dict[str, object], *, music: bool = True) -> str:
        old = self._songs[at]
        if music:
            # A song that changed is not the song that was approved.
            changes = {**changes, "verdict": Verdict.NONE}
        new = self._replace(at, changes)
        if new == old:
            return "it already is; nothing changed"
        baked = self._baked(old.title)
        self._commit([*self._songs[:at], new, *self._songs[at + 1 :]])
        if new.title != old.title and baked is not None and self._setlist is not None:
            # The title is how a spec finds its bake, so the bake is renamed with it.
            renamed = tuple(
                song.model_copy(update={"title": new.title}) if song is baked else song
                for song in self._setlist.songs
            )
            self._setlist = self._setlist.model_copy(update={"songs": renamed})
            save_setlist(self._setlist, self.bake)
        self._record("song_edited", title=new.title, fields=",".join(sorted(changes)))
        stale = music and baked is not None
        return f"{at + 1}. {new.title}: changed." + (
            f" It was written before this: compose {at + 1} to write it again." if stale else ""
        )

    def _list_styles(self, args: list[str]) -> str:
        if not self._styles:
            return f"no styles in {self._files.styles}"
        return "styles:\n" + "\n".join(
            f"  {style.name:<11} {style.summary}"
            + (f" ({style.reference})" if style.reference else "")
            for style in self._styles.values()
        )

    # ------------------------------------------------------ when the songwriter writes

    def _plan(self, at: int) -> Planned:
        return plan_song(self._songs[at], self._set_bpm, self._styles)

    def _compose(self, args: list[str]) -> str:
        if args[:1] == ["all"]:
            ats = [
                at
                for at, song in enumerate(self._songs)
                if self.state_of(song) in ("idea", "changed")
            ]
            if not ats:
                return "every song in the concert is written; redo N writes one again"
        else:
            ats = [self._at(args)]
            if self.state_of(self._songs[ats[0]]) not in ("idea", "changed"):
                return f"song {ats[0] + 1} is written as asked; redo {ats[0] + 1} writes it again"
        return self._ask_to_write(ats)

    def _ask_to_write(self, ats: list[int]) -> str:
        plans = [self._plan(at) for at in ats]
        calls = sum(len(song.asked) for song in plans)

        def write() -> str:
            said: list[str] = []
            answers = floor_answers(plans, songwriter=True) if self._fake else {}

            async def work(provider: LLMProvider) -> list[Song]:
                return [
                    await compose_song(
                        provider, self._model, song, said.append, label=song.spec.title
                    )
                    for song in plans
                ]

            songs = self._paid(answers, work)
            for song in songs:
                self._store(song)
                self._record(
                    "song_composed",
                    title=song.title,
                    model=self._model.id,
                    takes=len(song.takes),
                    missed=len(song.missed),
                    theme=bool(song.theme),
                )
            return "".join(said) + self._spent_line()

        titles = ", ".join(song.spec.title for song in plans)
        return self._gate(f"write {titles}", calls + len(plans), calls, len(plans), write)

    def _redo(self, args: list[str]) -> str:
        at = self._at(args)
        if len(args) == 1:
            return self._ask_to_write([at])
        asked = self._songs[at]
        baked = self._baked(asked.title)
        if baked is None:
            raise StudioError(f"song {at + 1} is not written yet: compose {at + 1}")
        if not composed_as(asked, baked, self._set_bpm):
            raise StudioError(f"song {at + 1} changed since it was written: compose {at + 1} first")
        kind, note = args[1].lower(), " ".join(args[2:])
        planned = planned_from(baked, direction_for(asked, self._styles))
        indices = [index for index in planned.asked if baked.form[index].name == kind]
        if not indices:
            kinds = sorted({baked.form[index].name for index in planned.asked})
            raise StudioError(
                f"{kind!r} is not a section the songwriter wrote in this song; it wrote: "
                + ", ".join(kinds)
            )

        def write() -> str:
            said: list[str] = []
            answers = floor_sections(planned, indices, baked.theme, note) if self._fake else {}

            async def work(provider: LLMProvider) -> tuple[Song, int]:
                return await redo(provider, self._model, baked, planned, indices, note, said.append)

            song, delivered = self._paid(answers, work)
            if delivered:
                # Swapped in as it is: `redo` already retired the takes it replaced.
                self._setlist = self._swap(song)
            self._record(
                "sections_redone", title=song.title, section=kind, delivered=delivered, note=note
            )
            return "".join(said) + self._spent_line()

        return self._gate(
            f"write the {kind} of {asked.title} again", len(indices), len(indices), 0, write
        )

    def _swap(self, song: Song) -> Setlist:
        """The bake with `song` exactly as given, its own `retired` included."""
        assert self._setlist is not None
        songs = tuple(song if each.title == song.title else each for each in self._setlist.songs)
        setlist = self._setlist.model_copy(update={"songs": songs})
        save_setlist(setlist, self.bake)
        return setlist

    def _gate(
        self, what: str, calls: int, sections: int, themes: int, write: Callable[[], str]
    ) -> str:
        """Do it now when it is free; otherwise say what it costs and wait for `yes`."""
        if self._fake:
            return write()
        left = self._cap - self._spent
        if left <= 0:
            return f"this session has spent its ${self._cap:.2f}; nothing sent"
        expected, bound = estimate(self._model, sections, songwriter=True, songs=themes)
        self._pending = write
        return (
            f"to {what}: {calls} call(s) to {self._model.id}, about ${expected:.2f}, at most "
            f"${min(bound, left):.2f}. This session has ${left:.2f} left. Type yes to go ahead."
        )

    def _paid[T](self, answers: dict[str, str], work: Callable[[LLMProvider], Awaitable[T]]) -> T:
        """Run `work` against the songwriter, under what is left of the session's cap."""
        left = self._cap - self._spent
        try:
            inner = BakedProvider(answers, name="fake") if self._fake else self._wiring.connect()
        except ProviderError as exc:
            raise StudioError(f"{exc}; nothing sent") from exc
        provider = guarded(inner, self._catalog, left if left > 0 else self._cap)

        async def session() -> T:
            # One loop for the whole job: the adapter's client binds to the first it is used on.
            if isinstance(provider, Warmable):
                with suppress(ProviderError):
                    await provider.warm()
            return await work(provider)

        try:
            return asyncio.run(session())
        finally:
            self._spent += _spent_by(provider)

    def _spent_line(self) -> str:
        return f"spent ${self._spent:.4f} of ${self._cap:.2f} this session\n"

    # --------------------------------------------------------------- which songs play

    def _listen(self, args: list[str]) -> str:
        at = self._at(args)
        asked = self._songs[at]
        if self._baked(asked.title) is None:
            raise StudioError(f"song {at + 1} is not written yet: compose {at + 1}")
        if self._wiring.listen is None:
            raise StudioError("no stage here: listening needs a terminal and Live")
        said = self._wiring.listen(self.bake, asked.title)
        # The stage may have written the keeps and vetoes struck while it played.
        self._setlist = load_setlist(self.bake)
        self._record("song_listened", title=asked.title)
        return said + f"approve {at + 1} or reject {at + 1} when you have decided.\n"

    def _judge(self, args: list[str], verdict: Verdict) -> str:
        at = self._at(args)
        asked = self._songs[at]
        if verdict is Verdict.APPROVED and self.state_of(asked) in ("idea", "changed"):
            raise StudioError(f"song {at + 1} is not written as asked yet: compose {at + 1}")
        new = self._replace(at, {"verdict": verdict, "parked": False})
        self._commit([*self._songs[:at], new, *self._songs[at + 1 :]])
        self._record(f"song_{verdict}", title=asked.title)
        return f"{at + 1}. {asked.title}: {verdict}. " + self._show_line()

    def _move(self, args: list[str]) -> str:
        at = self._at(args)
        to = self._at(args[1:])
        songs = list(self._songs)
        songs.insert(to, songs.pop(at))
        self._commit(songs)
        self._record("song_moved", title=songs[to].title, position=to + 1)
        return f"{songs[to].title} is now song {to + 1}"

    def _park(self, args: list[str], aside: bool) -> str:
        at = self._at(args)
        new = self._replace(at, {"parked": aside})
        self._commit([*self._songs[:at], new, *self._songs[at + 1 :]])
        self._record("song_set_aside" if aside else "song_brought_back", title=new.title)
        return f"{new.title}: " + (
            "set aside, out of the concert" if aside else "back in the concert"
        )

    def _delete(self, args: list[str]) -> str:
        at = self._at(args)
        gone = self._songs[at]
        self._commit([*self._songs[:at], *self._songs[at + 1 :]])
        self._record("song_deleted", title=gone.title)
        return (
            f"{gone.title}: out of the concert's file. "
            "What was written for it is kept; undo brings it back."
        )

    def _take_back(self, args: list[str]) -> str:
        if not self._undo:
            return "nothing to take back"
        songs = self._undo.pop()
        self._commit(songs, undoable=False)
        self._record("change_undone")
        return "taken back. What the songwriter wrote stays written."

    # ------------------------------------------------------------------ looking

    def _sheet(self, args: list[str]) -> str:
        at = self._at(args)
        asked = self._songs[at]
        bpm = self._set_bpm if asked.bpm is None else asked.bpm
        lines = [
            f"{asked.title}: {asked.style or 'no style'}, {render_key(asked.key, asked.scale)}, "
            f"{asked.feel}, {bpm:g} BPM, {self.state_of(asked)}"
        ]
        if asked.notes:
            lines.append(f"notes: {asked.notes}")
        baked = self._baked(asked.title)
        if baked is None:
            form = self._plan(at).form
            lines.append(f"form, as it would be arranged: {' '.join(s.name for s in form)}")
            return "\n".join(lines) + "\nnot written yet\n"
        lines.append(
            f"form ({clock(baked.total_seconds())}): {' '.join(s.name for s in baked.form)}"
        )
        lines.append(
            "material: a riff and two melodies of its own"
            if baked.theme
            else "material: none, so its sections were written with no riff or melody in hand"
        )
        takes = {take.briefing: take for take in baked.takes}
        wrote = [
            f"{section.name} {index + 1}"
            + (
                ""
                if takes[section].status is TakeStatus.UNMARKED
                else f" ({takes[section].status})"
            )
            for index, section in enumerate(baked.form)
            if section in takes
        ]
        floor = [f"{s.name} {i + 1}" for i, s in enumerate(baked.form) if s not in takes]
        lines.append("the songwriter wrote: " + (", ".join(wrote) or "nothing"))
        lines.append("the players cover: " + (", ".join(floor) or "nothing"))
        cost = sum((take.cost_usd for take in (*baked.takes, *baked.retired)), Decimal(0))
        lines.append(f"cost to write: ${cost:.4f}, {len(baked.retired)} earlier take(s) kept aside")
        return "\n".join(lines) + "\n"

    def _concerts(self, args: list[str]) -> str:
        folder = self._concert.parent
        if not args:
            found = sorted(folder.glob("*.toml"))
            return "concerts: " + (", ".join(path.stem for path in found) or "none yet")
        if len(args) < 2 or args[0] not in ("new", "open"):
            raise StudioError('concert, concert new "name" or concert open "name"')
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in args[1].lower()).strip("-")
        if not slug:
            raise StudioError("a concert's name needs a letter or a number")
        path = folder / f"{slug}.toml"
        if args[0] == "new" and path.exists():
            raise StudioError(f"{slug} already exists: concert open {slug}")
        if args[0] == "open" and not path.exists():
            raise StudioError(f"no concert called {slug}. " + self._concerts([]))
        self._open(path)
        return f'concert "{slug}"' + (": empty, start with new <style>" if not self._songs else "")

    def _cost(self, args: list[str]) -> str:
        songs = self._setlist.songs if self._setlist is not None else ()
        wrote = sum(
            (take.cost_usd for song in songs for take in (*song.takes, *song.retired)), Decimal(0)
        )
        return (
            f"this session: ${self._spent:.4f} of ${self._cap:.2f}. "
            f"The sections written for this concert so far cost ${wrote:.4f} "
            "(each song's material is one more call, not counted here)."
        )

    def _check(self, args: list[str]) -> str:
        if self._wiring.check is None:
            raise StudioError("no stage here: the check needs Live")
        return self._wiring.check(self.bake)

    def _show_line(self) -> str:
        playing = self._lineup()
        if not playing:
            return "The show has no songs yet."
        return "The show plays: " + ", ".join(song.title for song in playing) + "."

    def _show(self, args: list[str]) -> str:
        judged = any(song.verdict is not Verdict.NONE for song in self._songs)
        note = "" if judged else " No song has been judged yet, so every written song plays."
        return (
            f"{self._show_line()}{note}\n"
            f"quit, then: uv run garagem show --setlist {self.bake} --song 1"
        )

    def _quit(self, args: list[str]) -> str:
        self.done = True
        return "the concert is saved as it stands"


def _spent_by(provider: GuardedProvider) -> Decimal:
    return provider.governor.snapshot().spent_usd


def run_studio(studio: Studio, lines: TextIO, out: TextIO) -> int:
    """The screen, a typed line, what it did, and the screen again, until `quit`."""
    out.write(studio.screen())
    while not studio.done:
        out.write("> ")
        out.flush()
        line = lines.readline()
        if not line:
            break
        said = studio.execute(line)
        if studio.done:
            out.write(said.rstrip("\n") + "\n")
            break
        out.write("\n" + studio.screen())
        if said:
            out.write(said.rstrip("\n") + "\n")
    return 0
