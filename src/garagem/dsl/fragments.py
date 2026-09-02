"""Decoding one JSON string field out of a stream of fragments.

A `ToolInputDelta.fragment` is not JSON. It is a slice of a byte stream that will
eventually be JSON, and `json.loads` cannot help until the closing brace arrives — which
is exactly the moment at which incremental parsing has stopped being worth anything
(ADR-011).

So this decodes `{"dsl": "…"}` by hand, character by character, and hands back the new
characters of the value as they become certain. Hand-rolled rather than a streaming-JSON
dependency because the object has one field whose shape we wrote ourselves in
`dsl/schema.TOOL`, and the project is deliberately lean.

**The hard part is that a fragment can end anywhere**, including halfway through an
escape. Anthropic split one section into 45 fragments and none of them respect anything:
`\\n` can arrive as `…\\` and then `n…`. The rule this module follows is that it emits
nothing it might have to take back — a held half-escape produces no output at all until
the rest of it arrives, so a caller can append what it is given and never wonder.

A single fragment carrying the whole object (which is what Gemini 3.6 Flash sends) goes
through the identical path and must produce the identical result. That is a test, not a
hope.
"""

from __future__ import annotations

import re
from typing import Final

from garagem.dsl.errors import StreamProtocolError

# `"key" :` — the key itself may contain escapes, so match them rather than assuming not.
_KEY: Final = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:\s*')

# The eight escapes JSON defines besides `\uXXXX`.
ESCAPES: Final[dict[str, str]] = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}

_UNICODE_DIGITS: Final = 4
# `\uXXXX` is six characters, and all six have to be in hand before it means anything.
_UNICODE_LENGTH: Final = 6

_HIGH_SURROGATE = range(0xD800, 0xDC00)
_LOW_SURROGATE = range(0xDC00, 0xE000)


class StringField:
    """Accumulates fragments of `{"<field>": "…"}` and decodes the value as it arrives.

    Not a general JSON parser and not trying to be. It knows one object shape, refuses
    anything else, and its whole job is to never emit half of an escape.
    """

    def __init__(self, field: str = "dsl") -> None:
        self._field = field
        self._pending = ""
        self._decoded: list[str] = []
        self._started = False
        self._closed = False
        self._complete = False

    def feed(self, fragment: str) -> str:
        """Consume a fragment. Returns the *new* decoded characters, possibly none.

        Raises after the object is complete: a fragment arriving then means the stream
        and this decoder disagree about which message they are reading, and carrying on
        would silently corrupt a section.
        """
        if self._complete:
            raise StreamProtocolError(
                f"fragment after the tool input closed: {fragment!r}. "
                "The stream and the decoder disagree about which message this is."
            )
        self._pending += fragment
        produced: list[str] = []

        if not self._started:
            self._find_the_value()
        if self._started and not self._closed:
            produced = self._decode()
        if self._closed:
            self._find_the_end()

        self._decoded.extend(produced)
        return "".join(produced)

    @property
    def started(self) -> bool:
        """True once the value's opening quote has been seen."""
        return self._started

    @property
    def complete(self) -> bool:
        """True once the whole object has closed. Only then is `value()` the whole value."""
        return self._complete

    def value(self) -> str:
        """Everything decoded so far. Complete only when `complete` is true."""
        return "".join(self._decoded)

    # ------------------------------------------------------------------------ the states

    def _find_the_value(self) -> None:
        """Skip to the opening quote of our field, or refuse a field that is not ours."""
        match = _KEY.search(self._pending)
        if match is None:
            return
        key = match.group(1)
        if key != self._field:
            raise StreamProtocolError(
                f"the tool input has a {key!r} field; the schema declares only "
                f"{self._field!r} and forbids additional properties"
            )
        rest = self._pending[match.end() :]
        if not rest:
            return
        if not rest.startswith('"'):
            raise StreamProtocolError(
                f"{self._field!r} is not a string: it starts with {rest[0]!r}"
            )
        self._pending = rest[1:]
        self._started = True

    def _decode(self) -> list[str]:
        """Walk the pending text, emitting only what cannot change."""
        produced: list[str] = []
        index = 0
        pending = self._pending

        while index < len(pending):
            char = pending[index]
            if char == '"':
                index += 1
                self._closed = True
                break
            if char != "\\":
                produced.append(char)
                index += 1
                continue

            # An escape. Everything below either consumes the whole of it or stops and
            # waits — never half.
            if index + 1 >= len(pending):
                break
            marker = pending[index + 1]
            if marker == "u":
                if index + _UNICODE_LENGTH > len(pending):
                    break
                produced.append(self._unicode(pending[index + 2 : index + _UNICODE_LENGTH]))
                index += _UNICODE_LENGTH
                continue
            if marker not in ESCAPES:
                raise StreamProtocolError(f"\\{marker} is not a JSON escape")
            produced.append(ESCAPES[marker])
            index += 2

        self._pending = pending[index:]
        return produced

    def _unicode(self, digits: str) -> str:
        try:
            code = int(digits, 16)
        except ValueError:
            raise StreamProtocolError(f"\\u{digits} is not four hex digits") from None
        if code in _HIGH_SURROGATE or code in _LOW_SURROGATE:
            # A surrogate pair would need the next escape to mean anything, and nothing
            # in this DSL is outside the BMP. Refusing is honest; guessing is not.
            raise StreamProtocolError(
                f"\\u{digits} is a surrogate half; the GARAGEM DSL is ASCII and "
                "this decoder does not reassemble pairs"
            )
        return chr(code)

    def _find_the_end(self) -> None:
        """After the value: the object closes, and nothing else may be in it."""
        for index, char in enumerate(self._pending):
            if char == "}":
                self._pending = self._pending[index + 1 :]
                self._complete = True
                return
            if char == ",":
                raise StreamProtocolError(
                    "a second field after the value; the schema forbids additional properties"
                )
            if not char.isspace():
                raise StreamProtocolError(f"unexpected {char!r} after the value")


def decode_fragments(fragments: list[str], field: str = "dsl") -> str:
    """The whole value from a list of fragments. Convenience for tests and one-shot use."""
    decoder = StringField(field)
    for fragment in fragments:
        decoder.feed(fragment)
    if not decoder.complete:
        raise StreamProtocolError("the tool input never closed")
    return decoder.value()
