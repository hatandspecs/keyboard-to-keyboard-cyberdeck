"""Behaviour of the over-based transmit model (design_doc.md §5.4)."""
import session
from session import Session, RX, TX

FAILED = []

def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"          got  {got!r}\n          want {want!r}")
        FAILED.append(name)

def transcript(s):
    return [(e.who, e.text) for e in s.entries]

print("-- Enter composes, it does not transmit --")
s = Session(callsign="KD3CCO")
for ch in "hello there\n":
    check_out = s.type(ch)
check("nothing went on the air", s.compose, "hello there\n")
check("nothing in the transcript yet", transcript(s), [])
check("indicator counts the buffer", s.buffer_indicator(), "[RX 12]")

print("\n-- Ctrl-T sends the buffer and keys --")
out = s.start_over()
check("the buffered text is what goes out", out, "hello there\n")
check("state is transmitting", s.state, TX)
check("buffer is emptied", s.compose, "")
check("transcript attributes it to us", transcript(s), [("KD3CCO", "hello there")])
check("indicator shows TX", s.buffer_indicator(), "[TX]")

print("\n-- typing mid-over goes out live, character by character --")
sent = "".join(s.type(c) for c in "more")
check("each character is returned for sending", sent, "more")
check("and joins the same transcript line", transcript(s)[-1], ("KD3CCO", "more"))
check("buffer stays empty mid-over", s.compose, "")

print("\n-- Ctrl-K hands back --")
check("hand_back succeeds", s.hand_back(), True)
check("state returns to receive", s.state, RX)
check("the line is closed", s.entries[-1].closed, True)
check("hand_back again is a no-op", s.hand_back(), False)

print("\n-- received text is attributed to the far end --")
s.receive("W3TM de ")
s.receive("KD3CCO copy\n")
check("RX text accumulates into one line", transcript(s)[-1], ("RX", "W3TM de KD3CCO copy"))
# Typing while receiving does not touch the transcript: it goes into the
# compose buffer and is shown at the bottom of the screen. It only becomes a
# transcript entry when the over starts.
s.type("x")
check("typing while receiving stays out of the transcript", transcript(s)[-1][0], "RX")
check("and lands in the compose buffer", s.compose, "x")
check("then appears when the over starts", (s.start_over(), transcript(s)[-1]),
      ("x", ("KD3CCO", "x")))

print("\n-- backspace corrects while receiving, not mid-over --")
s2 = Session(callsign="KD3CCO")
for ch in "helo":
    s2.type(ch)
check("backspace works while composing", (s2.backspace(), s2.compose), (True, "hel"))
s2.start_over()
check("backspace refused mid-over", s2.backspace(), False)

print("\n-- abort stops immediately and says so --")
check("abort while transmitting reports True", s2.abort(), True)
check("state is receive", s2.state, RX)
check("a marker is in the transcript", s2.entries[-1].who, "--")
check("abort while receiving reports False", s2.abort(), False)

print("\n-- transmit time-out --")
now = [0.0]
s3 = Session(callsign="KD3CCO", tx_timeout=180, clock=lambda: now[0])
s3.type("a"); s3.start_over()
now[0] = 179.0; check("not yet timed out at 179 s", s3.tx_timed_out(), False)
now[0] = 181.0; check("timed out at 181 s", s3.tx_timed_out(), True)
s4 = Session(callsign="KD3CCO", tx_timeout=0, clock=lambda: now[0])
s4.type("a"); s4.start_over()
check("TX_TIMEOUT = 0 never times out", s4.tx_timed_out(), False)

print("\n-- newlines close entries so speakers do not merge --")
s5 = Session(callsign="KD3CCO")
s5.receive("one\ntwo\n")
check("two separate received lines", transcript(s5), [("RX", "one"), ("RX", "two")])

print("\n-- scrollback is bounded --")
s6 = Session(callsign="KD3CCO", scrollback=100)
for i in range(500):
    s6.note(f"line {i}")
check("held at the limit", len(s6.entries), 100)
check("oldest dropped, newest kept", s6.entries[-1].text, "line 499")

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
