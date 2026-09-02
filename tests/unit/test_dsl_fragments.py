"""Decoding one JSON string out of fragments that end anywhere.

The rule the whole module exists to keep is negative: **it never emits anything it might
have to take back.** A fragment ending halfway through `\\n` produces nothing at all
until the rest arrives — so a caller can append what it is handed and never wonder.

The other assertion worth reading is the one that feeds the same object as 45 fragments
and as one, and demands the same answer. Anthropic sends 45 and Gemini sends 1, and the
decoder is not told which.
"""

from __future__ import annotations

import json

import pytest

from garagem.dsl.errors import StreamProtocolError
from garagem.dsl.fragments import StringField, decode_fragments

DSL = (
    "SEC verse bars=8 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4\n"
    "CHD | Em | C | G | D |\n"
    "DRM K:x..x..x...x..x.. S:....x.......x... H:x.x.x.x.x.x.x.x.\n"
)
OBJECT = json.dumps({"dsl": DSL})


def in_pieces(text: str, size: int) -> list[str]:
    return [text[at : at + size] for at in range(0, len(text), size)]


# ------------------------------------------------------------------------- the round trip


def test_a_value_split_across_fragments_decodes() -> None:
    assert decode_fragments(in_pieces(OBJECT, 7)) == DSL


@pytest.mark.parametrize("size", [1, 2, 3, 5, 11, 64, 4096])
def test_the_answer_does_not_depend_on_where_the_fragments_fall(size: int) -> None:
    """45 fragments and 1 fragment are the two real cases, and every size between."""
    assert decode_fragments(in_pieces(OBJECT, size)) == DSL


def test_one_fragment_carrying_everything_is_the_same_as_many() -> None:
    """Gemini 3.6 Flash sends the whole tool input at once; Anthropic sends 45 pieces."""
    assert decode_fragments([OBJECT]) == decode_fragments(in_pieces(OBJECT, 1))


def test_feeding_returns_only_what_is_new() -> None:
    decoder = StringField()
    produced = "".join(decoder.feed(piece) for piece in in_pieces(OBJECT, 9))
    assert produced == DSL
    assert decoder.value() == DSL


# ------------------------------------------------------------------------------- escapes


def test_a_newline_escape_split_across_a_boundary_never_leaks_a_backslash() -> None:
    """The single most likely bug in the phase, asserted directly."""
    decoder = StringField()
    assert decoder.feed('{"dsl": "a\\') == "a"
    assert decoder.feed('nb"}') == "\nb"
    assert decoder.value() == "a\nb"


def test_a_fragment_ending_mid_escape_produces_nothing_until_it_completes() -> None:
    decoder = StringField()
    decoder.feed('{"dsl": "x')
    assert decoder.feed("\\") == ""
    assert decoder.feed("t") == "\t"


def test_an_escaped_quote_does_not_end_the_string() -> None:
    decoder = StringField()
    decoder.feed(r'{"dsl": "he said \"go\" then"}')
    assert decoder.value() == 'he said "go" then'
    assert decoder.complete


def test_an_escaped_backslash_before_a_quote_does_not_escape_it() -> None:
    decoder = StringField()
    decoder.feed('{"dsl": "back\\\\"}')
    assert decoder.value() == "back\\"
    assert decoder.complete


@pytest.mark.parametrize(
    ("escape", "expected"), [("n", "\n"), ("t", "\t"), ("r", "\r"), ("/", "/"), ("b", "\b")]
)
def test_every_json_escape_decodes(escape: str, expected: str) -> None:
    assert decode_fragments([f'{{"dsl": "\\{escape}"}}']) == expected


def test_a_unicode_escape_decodes_across_a_boundary() -> None:
    decoder = StringField()
    decoder.feed('{"dsl": "\\u00e')
    assert decoder.value() == ""
    decoder.feed('9"}')
    assert decoder.value() == "é"


def test_an_escape_json_does_not_define_is_refused() -> None:
    with pytest.raises(StreamProtocolError, match=r"\\q"):
        decode_fragments([r'{"dsl": "a\q"}'])


def test_a_surrogate_half_is_refused_rather_than_guessed_at() -> None:
    """Nothing in this DSL is outside the BMP, so guessing would be inventing."""
    with pytest.raises(StreamProtocolError, match="surrogate"):
        decode_fragments(['{"dsl": "\\ud83d"}'])


def test_a_unicode_escape_that_is_not_hex_is_refused() -> None:
    with pytest.raises(StreamProtocolError, match="hex"):
        decode_fragments(['{"dsl": "\\uzzzz"}'])


# -------------------------------------------------------------------------- the object


def test_the_empty_fragment_is_a_no_op() -> None:
    decoder = StringField()
    assert decoder.feed("") == ""
    assert not decoder.started


def test_complete_flips_only_at_the_closing_brace() -> None:
    decoder = StringField()
    decoder.feed('{"dsl": "abc"')
    assert not decoder.complete
    decoder.feed("}")
    assert decoder.complete


def test_a_field_that_is_not_ours_is_refused_by_name() -> None:
    """The schema declares one property and forbids the rest; so does this."""
    with pytest.raises(StreamProtocolError, match="'notes'"):
        decode_fragments(['{"notes": "…"}'])


def test_a_second_field_after_the_value_is_refused() -> None:
    with pytest.raises(StreamProtocolError, match="second field"):
        decode_fragments(['{"dsl": "a", "extra": 1}'])


def test_a_value_that_is_not_a_string_is_refused() -> None:
    with pytest.raises(StreamProtocolError, match="not a string"):
        decode_fragments(['{"dsl": 12}'])


def test_a_stream_that_never_closes_says_so() -> None:
    with pytest.raises(StreamProtocolError, match="never closed"):
        decode_fragments(['{"dsl": "half a sec'])


def test_feeding_after_the_object_closed_is_refused() -> None:
    """The stream and the decoder disagree about which message this is."""
    decoder = StringField()
    decoder.feed('{"dsl": "a"}')
    with pytest.raises(StreamProtocolError, match="after the tool input closed"):
        decoder.feed("more")


# --------------------------------------------------------------------- the real cassette


def test_the_recorded_anthropic_fragments_decode_to_a_whole_section() -> None:
    """45 fragments from a real model, replayed with no network."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    fragments = [
        json.loads(line)["fragment"]
        for line in (root / "cassettes" / "anthropic_section.jsonl").read_text().splitlines()
        if '"tool_input_delta"' in line
    ]
    assert len(fragments) > 40
    decoded = decode_fragments(fragments)
    assert decoded.splitlines()[0].startswith("SEC verse")
    assert [line.split()[0] for line in decoded.splitlines()] == [
        "SEC",
        "CHD",
        "DRM",
        "BAS",
        "GTR",
        "KEY",
    ]
