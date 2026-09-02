"""Incremental parser, serializer and tool-use schemas for the symbolic DSL."""

from garagem.dsl.errors import DslError, LineError, StreamProtocolError
from garagem.dsl.fragments import ESCAPES, StringField, decode_fragments
from garagem.dsl.lines import (
    PARSE_RULES,
    BarLine,
    BassLine,
    ChordLine,
    DrumLine,
    check_chd,
    check_sec,
    parse_bar_line,
    parse_chd,
    parse_sec,
)
from garagem.dsl.realise import realise
from garagem.dsl.schema import SYSTEM, SYSTEM_ARRANGED, TOOL, brief, system_for
from garagem.dsl.serialize import serialize_score, serialize_section
from garagem.dsl.stream import ORDER, ParsedSection, SectionStream, parse_section

__all__ = [
    "ESCAPES",
    "ORDER",
    "PARSE_RULES",
    "SYSTEM",
    "SYSTEM_ARRANGED",
    "TOOL",
    "BarLine",
    "BassLine",
    "ChordLine",
    "DrumLine",
    "DslError",
    "LineError",
    "ParsedSection",
    "SectionStream",
    "StreamProtocolError",
    "StringField",
    "brief",
    "check_chd",
    "check_sec",
    "decode_fragments",
    "parse_bar_line",
    "parse_chd",
    "parse_sec",
    "parse_section",
    "realise",
    "serialize_score",
    "serialize_section",
    "system_for",
]
