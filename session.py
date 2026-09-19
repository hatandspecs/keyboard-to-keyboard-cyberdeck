"""The conversation: transcript, compose buffer, and the shape of an over.

Kept free of curses so the behaviour that matters can be tested without a
terminal. The interface in cyberdeck.py renders what is here and does nothing
else with it.

The transmit model is the over-based one settled in design_doc.md §5.4, which
is fldigi's norm and HF's norm and is not what intuition suggests:

    compose while receiving  ->  Ctrl-T starts the over  ->  Ctrl-K hands back

Enter inserts a newline into the buffer. It does not transmit. Sending a line
at a time would key the rig dozens of times per QSO, and every turnaround
costs seconds of settling at both ends.

Once an over is running, characters go out as they are typed. That live
typing, corrections included, is what makes this keyboard-to-keyboard rather
than messaging.
"""

import time
from collections import deque

RX = "rx"      # receiving; the buffer accumulates and nothing is transmitted
TX = "tx"      # an over is running; typing goes straight out


class Entry:
    """One run of text from one station, possibly still being added to."""

    __slots__ = ("when", "who", "text", "closed")

    def __init__(self, who, text="", when=None):
        self.when = when if when is not None else time.time()
        self.who = who
        self.text = text
        self.closed = False

    def __repr__(self):
        return f"<{self.who}: {self.text!r}{' ' if self.closed else ' open'}>"


class Session:
    def __init__(self, callsign="", scrollback=2000, tx_timeout=180,
                 clock=time.monotonic):
        self.callsign = callsign or "LOCAL"
        self.entries = deque(maxlen=scrollback)
        self.compose = ""
        self.state = RX
        self.tx_timeout = tx_timeout
        self._clock = clock
        self._tx_started = None
        self.notices = deque(maxlen=50)
        # Transmit inhibit. Enforced here rather than by asking fldigi to
        # enforce it: fldigi's main.rx_only was observed not to stop
        # main.tune, and a safety property that depends on another process
        # behaving as documented is not a safety property. Nothing downstream
        # is asked to key unless this is False.
        self.inhibited = False

    # -- transcript -------------------------------------------------------

    def _append(self, who, text):
        """Add text attributed to `who`, continuing an open entry from the
        same station rather than starting a new one for every character."""
        if not text:
            return
        for i, part in enumerate(text.split("\n")):
            if i:
                # A newline closes whatever was open.
                if self.entries and not self.entries[-1].closed:
                    self.entries[-1].closed = True
            if not part:
                continue
            last = self.entries[-1] if self.entries else None
            if last is not None and not last.closed and last.who == who:
                last.text += part
            else:
                self.entries.append(Entry(who, part))

    def receive(self, text):
        """Text decoded off the air. Attributed to the far end, which is not
        identified — the transcript shows who is not this station, and the
        callsign of the other operator is whatever they type."""
        self._append("RX", text)

    def note(self, text):
        """A marker in the transcript: a mode change, a warning. Closed
        immediately, so nothing else joins it."""
        entry = Entry("--", text)
        entry.closed = True
        self.entries.append(entry)
        self.notices.append(text)

    # -- composing --------------------------------------------------------

    def type(self, char):
        """A printable character or a newline from the keyboard.

        Returns the text that should go on the air right now: everything while
        an over is running, nothing while receiving.
        """
        self.compose += char
        if self.state == TX:
            out, self.compose = self.compose, ""
            self._append(self.callsign, out)
            return out
        return ""

    def backspace(self):
        """Correct the composed buffer.

        Only meaningful while receiving. Mid-over the characters have already
        been sent, and the far end has seen them — which is how RTTY chat has
        always worked, and is not a bug to be hidden.
        """
        if self.state == RX and self.compose:
            self.compose = self.compose[:-1]
            return True
        return False

    # -- the over ---------------------------------------------------------

    def inhibit(self, on=True):
        """Refuse to transmit at all. Survives a hand-back and an abort;
        only an explicit call clears it."""
        self.inhibited = bool(on)
        self.note("transmit inhibited" if self.inhibited else "transmit enabled")
        return self.inhibited

    def start_over(self):
        """Begin transmitting. Returns the buffered text to send, or None if
        no over was started — already transmitting, or inhibited."""
        if self.inhibited:
            self.note("transmit inhibited — nothing sent")
            return None
        if self.state == TX:
            return None
        text, self.compose = self.compose, ""
        self.state = TX
        self._tx_started = self._clock()
        if text:
            self._append(self.callsign, text)
        return text

    def hand_back(self):
        """End the over. fldigi drops to receive once the buffer drains."""
        if self.state != TX:
            return False
        self.state = RX
        self._tx_started = None
        if self.entries and not self.entries[-1].closed:
            self.entries[-1].closed = True
        return True

    def abort(self):
        """Stop transmitting immediately, mid-word if necessary."""
        was = self.state == TX
        self.state = RX
        self._tx_started = None
        if was:
            self.note("transmit aborted")
        return was

    def tx_elapsed(self):
        if self._tx_started is None:
            return 0.0
        return self._clock() - self._tx_started

    def tx_timed_out(self):
        """True when an over has run past TX_TIMEOUT and must be stopped.

        The radio's own timer is the real backstop; this is the software one,
        and it exists because a host that hangs holds PTT asserted.
        """
        if self.state != TX or not self.tx_timeout:
            return False
        return self.tx_elapsed() >= self.tx_timeout

    # -- what the interface shows -----------------------------------------

    def buffer_indicator(self):
        if self.state == TX:
            return "[TX]"
        return f"[RX {len(self.compose)}]" if self.compose else "[RX]"
