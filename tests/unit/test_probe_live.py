"""The probe's one promise: it reads, and it changes nothing.

`probe_live.py` is run against a real Live, by hand, when something is wrong. That is
exactly when it must not make things worse — so the classification of which addresses it
will actually send is worth a test even though the script itself talks to a socket.

Phase 2 added three addresses that mutate no clip and no track, and still must not be
probed: `start_listen/beat` leaves a listener running in Live behind it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from garagem.daw.abletonosc import (
    ALL_ADDRESSES,
    GET_BEAT,
    GET_TEMPO,
    SET_TEMPO,
    START_LISTEN_BEAT,
    STOP_LISTEN_BEAT,
)

ROOT = Path(__file__).resolve().parents[2]


def _load_probe() -> ModuleType:
    path = ROOT / "scripts" / "probe_live.py"
    spec = importlib.util.spec_from_file_location("probe_live", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["probe_live"] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


def test_a_getter_is_probed() -> None:
    assert probe.is_read_only(GET_TEMPO)


def test_a_setter_is_not() -> None:
    assert not probe.is_read_only(SET_TEMPO)


def test_the_listener_addresses_are_not_probed() -> None:
    """They leave a listener running in Live, which a read-only probe must not do."""
    assert not probe.is_read_only(START_LISTEN_BEAT)
    assert not probe.is_read_only(STOP_LISTEN_BEAT)


def test_the_pushed_beat_address_is_not_probed_because_nothing_answers_it() -> None:
    """AbletonOSC never calls `add_handler` for it — `song.py` only ever `send`s on it.

    Asking would time out, and down here a timeout looks exactly like a wrong address.
    The probe would report the beat mechanism as broken while it worked perfectly.
    """
    assert not probe.is_read_only(GET_BEAT)
    assert GET_BEAT in probe.PUSH_ONLY


def test_every_address_the_adapter_uses_is_classified() -> None:
    """A new address that nobody classified would be probed by accident."""
    assert set(probe.WRITES) | set(probe.PUSH_ONLY) <= set(ALL_ADDRESSES)
    assert all(isinstance(probe.is_read_only(address), bool) for address in ALL_ADDRESSES)
