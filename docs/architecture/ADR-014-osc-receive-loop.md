# ADR-014 — One receive loop for the OSC socket

Status: **accepted** · Date: 2026-08-30 · Supersedes the "no dispatcher" paragraph in
`src/garagem/daw/osc.py`'s module docstring.

## Context

Phase 1 built the OSC transport around a single shape: one request, one correlated
reply, one deadline. `osc.py`'s docstring justified refusing `python-osc`'s servers in
those terms, and the justification ended with a claim that was true when it was written:

> Its servers ... are built to receive a stream of unsolicited messages and dispatch
> them to handlers, which would mean a background thread, a queue and a way to correlate
> a reply with the request that caused it. What this layer actually needs is one bounded
> round trip with a timeout, which is a socket and eight lines.

**Phase 2 needs the stream of unsolicited messages.** ADR-015 decides that the BarClock
follows beats Live pushes rather than a position it polls, and the mechanism is
`/live/song/start_listen/beat`. AbletonOSC's `song.py` registers
`add_current_song_time_listener`, and on every integer beat — or on a rewind — sends
`/live/song/get/beat` with the beat number, unprompted, to port 11001. At 132 BPM that
is one datagram every 455 ms, arriving forever, with nobody having asked for it.

The current `request()` would destroy every one of them, in two separate places, both of
which are correct for request/response:

1. It **drains** the socket non-blockingly before sending, so that a late reply to a
   previous call is never read as this one's. Every beat that arrived since the last
   request is thrown away there.
2. It **discards** replies whose address does not match the one it is waiting for. A
   beat landing during a request is read, found irrelevant, and dropped.

So the two mechanisms that make correlation reliable are exactly the two that make
listening impossible. This is not a bug to patch; it is the wrong shape for the traffic
the system now carries.

The alternative — polling — is what the Phase 1 measurements rule out. Every OSC round
trip on this machine costs about **100 ms**, measured across fifteen addresses on
localhost. That is not network latency; it is Live's control-surface thread ticking at
100 Hz. A clock built on polling would have 100 ms granularity, would consume the same
thread it was trying to observe, and would get worse under exactly the load that makes
timing matter.

## Decision

**One background receive thread owns `recvfrom`, and routes every datagram.**

- A datagram whose address has a **waiting caller** is placed in that caller's slot and
  its `Event` is set. `request()` becomes: register a waiter, send once, wait on the
  event with the remaining budget, collect. No draining, because nothing else reads the
  socket any more; no discarding, because routing replaces filtering.
- A datagram whose address has a **registered listener** is handed to it.
- Anything else increments a `dropped` counter and is discarded. The counter is
  observable, because silently dropping messages is how this layer would lie.

`OscTransport` gains `listen(address, handler)` and `unlisten(address)`.

**The handler runs on the receive thread, and must do no musical work.** It stores a
value, sets an `Event`, and returns. Everything that follows from a beat — deciding to
write a section, deciding to fire a scene — happens on the thread that was waiting.
That is P1's boundary in its literal form: the two clocks meet at a data structure and a
signal, never at a call that could block one of them on the other.

A handler that raises does **not** kill the loop. It increments a counter and the loop
continues, because a dead receive thread does not announce itself: it presents as Live
having gone quiet, which is the one failure mode this system already treats as normal.

## Rejected alternatives

**Polling `song_time_beats()` in a loop.** ~100 ms per call, against a 1.82 s bar; five
calls a second to get bar-level information Live is willing to push for free; and the
jitter grows precisely when the control-surface thread is busy — which is when we are
writing clips. Rejected on the measurement, not on taste.

**`python-osc`'s `ThreadingOSCUDPServer` plus its `Dispatcher`.** This is the thing the
original docstring declined, and it is still declined, for a reason that has not changed:
it wants to own a socket, and replies from AbletonOSC always arrive at port 11001. Two
owners of one port cannot coexist, so adopting the server would mean routing our
request/response traffic through its dispatcher anyway — the same correlation problem,
solved twice, with a dependency's threading model in the middle.

**`asyncio`.** `realtime.md` forbids awaiting I/O on this path, and ADR-013 chose a
synchronous port deliberately: the only consumer is `transport/`, OSC is bounded
request/response, and there is no streaming for an event loop to buy. Introducing one
here to solve a threading problem would invert that decision to gain nothing.

**Keeping `request()` as it is and adding a second socket for listening.** The reply port
is fixed at 11001 for everything, so there is no second port to listen on.

## Consequences

- **The transport owns a thread**, so `close()` stops meaning "release a file
  descriptor" and starts meaning "signal the loop and join it". It is a daemon thread, so
  a stuck join cannot hang the interpreter.
- **`FakeOscTransport` gains `deliver(address, args)`.** Without it the fake could no
  longer reproduce Live, and the offline suite would stop being evidence for the online
  behaviour — which is the property that made Phase 1 close on its first live attempt.
- **`dropped` becomes an observable**, and Phase 2's findings should report whether it is
  ever non-zero during a run. A beat lost to a full buffer is a real thing to know.
- **Beat loss is self-healing and needs no recovery code.** AbletonOSC sends absolute
  beat numbers, not deltas, so a dropped datagram costs one late decision and the next
  message resyncs. The BarClock exploits this (ADR-015) rather than counting.
- **Exactly one process can talk to Live**, now for a second reason: not only is 11001
  the only reply port, it is now continuously occupied by a reader.
- The request/response contract does **not** change. Every existing `osc` and
  `abletonosc` test must pass unaltered; if one needs editing, the change went further
  than this decision allows.
