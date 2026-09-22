"""Key sequences an operator actually produces, in orders nobody designed for.

Everything here came from one evening of real use. The over model has three
keys and they can be pressed in any order, at any moment, including while the
radio is still emptying a buffer the operator can no longer see. What matters
is not that each key works but that no ordering of them leaves the terminal in
a state it cannot describe or leave.

The invariants, checked after every sequence:

  * TX implies the time-out is armed. A transmit nobody is timing is the one
    state that can put a signal on the air indefinitely.
  * The time-out is disarmed only by an abort or by the radio confirming it
    stopped, never by a key that merely expresses intent.
  * Every refused action says why. A key that does nothing in silence is
    indistinguishable from a broken one, which cost an evening once already.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
from session import Session, RX, TX


def deck(timeout=180):
    clock = [0.0]
    s = Session(callsign="KD3CCO", tx_timeout=timeout, clock=lambda: clock[0])
    return s, clock


def armed(s):
    return s._tx_started is not None


def invariants(label, s):
    """Hold after every sequence, whatever it was."""
    if s.state == TX:
        check(f"{label}: transmitting implies the time-out is armed", armed(s),
              "a transmit nobody is timing")
    check(f"{label}: state is one of RX/TX", s.state in (RX, TX), s.state)


if __name__ == "__main__":
    print("Unusual key sequences")

    # --- the one he hit: over, hand, then over again to add more -----------
    s, clock = deck()
    s.type("first"); s.start_over()
    clock[0] = 2.0
    s.hand_back()
    equals("after hand back the session is receiving", s.state, RX)
    check("but the time-out is still armed, because the radio may be keyed",
          armed(s))
    clock[0] = 3.0
    s.type("more")
    second = s.start_over()
    equals("the session itself allows a second over", second, "more")
    invariants("over/hand/over", s)

    # The session cannot know fldigi still holds an unsent "^r"; the terminal
    # does, and refuses there. What is checked here is that the session does
    # not additionally corrupt itself.
    entries = list(s.entries)          # a deque: not sliceable
    check("and the first over is closed in the transcript",
          all(e.closed for e in entries[:-1]) or len(entries) <= 1)

    # --- hand twice --------------------------------------------------------
    s, clock = deck()
    s.type("x"); s.start_over(); s.hand_back()
    equals("a second hand back is refused", s.hand_back(), False)
    invariants("hand twice", s)

    # --- abort during the drain -------------------------------------------
    s, clock = deck()
    s.type("x"); s.start_over(); s.hand_back()
    equals("abort during the drain reports it stopped something", s.abort(), True)
    check("and disarms the time-out", not armed(s))
    invariants("abort mid-drain", s)

    # --- abort, then start again ------------------------------------------
    s, clock = deck()
    s.type("x"); s.start_over(); s.abort()
    s.type("y")
    check("a new over can start after an abort", s.start_over() is not None)
    invariants("abort then over", s)

    # --- keys with nothing running ----------------------------------------
    s, clock = deck()
    equals("hand back with nothing running is refused", s.hand_back(), False)
    equals("abort with nothing running is refused", s.abort(), False)
    check("and neither arms the time-out", not armed(s))
    invariants("idle keys", s)

    # --- a second over while the first is running -------------------------
    s, clock = deck()
    s.type("one"); s.start_over()
    s.type("two")
    equals("a second over while transmitting is refused", s.start_over(), None)
    check("and says why", "already transmitting" in (s.last_note or ""),
          s.last_note)
    invariants("double over", s)

    # --- inhibit mid-over --------------------------------------------------
    s, clock = deck()
    s.type("x"); s.start_over()
    s.inhibit(True)
    equals("inhibiting does not end the over", s.state, TX)
    check("and the time-out stays armed", armed(s))
    invariants("inhibit mid-over", s)
    # It does block the next one.
    s.abort(); s.type("y")
    equals("the next over is then refused", s.start_over(), None)
    check("with the reason given", "inhibited" in (s.last_note or ""),
          s.last_note)

    # --- an empty over, then typing live ----------------------------------
    # Legitimate: key up and type straight onto the air, which is how RTTY was
    # worked long before buffers. It must not be mistaken for a no-op.
    s, clock = deck()
    empty = s.start_over()
    equals("an empty over is allowed", empty, "")
    equals("and it is a real transmit state", s.state, TX)
    check("with the time-out armed", armed(s))
    equals("typing then goes straight out", s.type("a"), "a")
    invariants("empty over", s)

    # --- the time-out fires during a drain --------------------------------
    s, clock = deck()
    s.type("x"); s.start_over()
    clock[0] = 1.0; s.hand_back()
    clock[0] = 181.0
    check("a drain that never ends still times out", s.tx_timed_out())
    s.abort()
    check("and aborting clears it", not s.tx_timed_out())
    invariants("drain time-out", s)

    # --- resync, then normal use ------------------------------------------
    s, clock = deck()
    s.type("x"); s.start_over()
    check("resync drops a phantom transmit", s.resync_to_receive())
    check("the time-out is disarmed with it", not armed(s))
    s.type("y")
    check("and the next over starts normally", s.start_over() is not None)
    invariants("after resync", s)

    sys.exit(report())
