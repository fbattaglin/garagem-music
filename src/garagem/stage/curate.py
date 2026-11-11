"""Curation: the keeps and vetoes a performance logged, written into its setlist (ADR-024).

Moved here from `scripts/curate_setlist.py` when the studio needed it (ADR-030): a song
listened to from the studio has its marks saved when it ends, with no second command. The
script imports it back, so both curate by one rule.
"""

from __future__ import annotations

from collections import Counter

from garagem.obs import Mark
from garagem.setlist import Setlist, TakeStatus, body

STATUS = {"keep": TakeStatus.KEPT, "veto": TakeStatus.VETOED}


def curate(setlist: Setlist, found: list[Mark]) -> tuple[Setlist, Counter[str]]:
    """The setlist with every mark struck during its songs applied, and what happened to each."""
    tally: Counter[str] = Counter()
    decided: dict[tuple[int, str], TakeStatus] = {}
    for mark in found:
        if mark.setlist != setlist.name or mark.song is None:
            continue
        if not 1 <= mark.song <= len(setlist.songs):
            tally["no_such_song"] += 1
            continue
        if mark.dsl is None:
            tally[f"{mark.mark} on the floor"] += 1
            continue
        song = setlist.songs[mark.song - 1]
        if not any(body(take.dsl) == body(mark.dsl) for take in song.takes):
            tally[f"{mark.mark} on a take no longer here"] += 1
            continue
        decided[(mark.song, body(mark.dsl))] = STATUS[mark.mark]
        tally[mark.mark] += 1

    songs = []
    for number, song in enumerate(setlist.songs, start=1):
        takes = tuple(
            take.model_copy(update={"status": decided[(number, body(take.dsl))]})
            if (number, body(take.dsl)) in decided
            else take
            for take in song.takes
        )
        songs.append(song.model_copy(update={"takes": takes}))
    return setlist.model_copy(update={"songs": tuple(songs)}), tally
