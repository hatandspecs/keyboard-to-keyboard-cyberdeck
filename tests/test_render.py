"""Layout at every grid the panel can produce (docs/design_doc.md §3.3)."""
import os
import sys

# src/ holds the application; tests/ holds this. Both are addressed from the
# project root so a test can be run from anywhere.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT, "src")
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check, equals, report
import time, render
from render import plain
from session import Session


GRIDS = [(66, 20), (80, 24), (50, 15), (100, 30)]

print("-- status line fits every grid, and never loses call/state/clock --")
fields = dict(call="KD3CCO", freq="14.070.15", sideband="USB", mode="BPSK31",
              carrier="1500Hz", snr="S/N 18", imd="IMD -24", state="RX", clock="2114Z")
for w, _ in GRIDS:
    line = plain(render.status_line(fields, w))
    ok = len(line) == w and "KD3CCO" in line and "RX" in line and "2114Z" in line
    check(f"{w} cols", ok, f"len={len(line)} {line!r}")

print("\n-- narrow widths drop the least useful fields first --")
for w in (66, 50, 40, 30):
    line = plain(render.status_line(fields, w))
    kept = [k for k in ("IMD", "USB", "S/N", "1500Hz", "14.070.15", "BPSK31") if k in line]
    print(f"    {w:3} cols: {line.strip()!r}")
    check(f"{w} cols still shows call+state", "KD3CCO" in line and "RX" in line)

print("\n-- transcript wraps and pads to the window height --")
s = Session(callsign="KD3CCO")
s.receive("KD3CCO de NOCALL  good copy, 599 here in State College. "
          "rig is an FTX-1 running 20 watts into a vertical.\n")
for c in "NOCALL de KD3CCO  copy 100 percent": s.type(c)
s.start_over()
lines = render.transcript_lines(s.entries, 66, 12)
check("exactly the window height", len(lines) == 12, f"got {len(lines)}")
check("no line exceeds the width", all(len(plain(l)) <= 66 for l in lines),
      max((len(plain(l)) for l in lines), default=0))
print("    sample:")
for l in lines[:5]:
    if plain(l).strip(): print(f"      |{plain(l)}|")

print("\n-- a long unbroken run is split rather than overflowing --")
s2 = Session(callsign="KD3CCO")
s2.receive("x" * 200)
lines = render.transcript_lines(s2.entries, 66, 8)
check("still within width", all(len(plain(l)) <= 66 for l in lines))

print("\n-- timestamps can be switched off, and the gutter shrinks --")
with_ts = plain(render.transcript_lines(s.entries, 66, 3, timestamps=True)[0])
without  = plain(render.transcript_lines(s.entries, 66, 3, timestamps=False)[0])
check("both fit", len(with_ts) <= 66 and len(without) <= 66)

print("\n-- compose region: indicator right-aligned, cursor after the text --")
lines, (row, col) = render.compose_lines("NOCALL de KD3CCO  all the fldigi modes", "[RX 36]", 66, 2)
check("height honoured", len(lines) == 2, len(lines))
# The indicator sits on the last *used* row, not on the padding below it.
check("indicator present", any("[RX 36]" in plain(l) for l in lines))
check("indicator is on the cursor row", "[RX 36]" in plain(lines[row]))
check("cursor on the last used row", row == 0, row)
first = plain(lines[0])
check("no overflow", all(len(plain(l)) <= 66 for l in lines), max(len(plain(l)) for l in lines))
print(f"    |{first}|")

print("\n-- empty transcript still fills the window --")
check("padded", len(render.transcript_lines([], 66, 10)) == 10)

print("\n-- the tuning screen's decode preview --")
equals("empty shows a dash", render.preview("", 40), "\u2014")
equals("keeps the tail, not the head",
       render.preview("A" * 10 + "TAIL", 4), "TAIL")
equals("collapses newlines into one line",
       render.preview("de N3QE\nK\n", 40), "de N3QE K")
equals("drops control characters",
       render.preview("ab\x00\x07cd", 40), "ab cd")
equals("narrow width returns nothing rather than garbage",
       render.preview("anything", 2), "")

print("\n-- signal readouts are not relabelled --")
rows = render.tune_rows({"snr": "45 /170", "imd": "s/n -22 dB"}, 66)
signal = [r for r in rows if r.startswith("  signal")][0]
check("RTTY's baud/shift survives verbatim", "45 /170" in signal, signal)
check("and is not prefixed with S/N", "S/N  45" not in signal, signal)

print("\n-- scroll back through history --")
s3 = Session(callsign="KD3CCO")
for i in range(40): s3.note(f"line {i}")
tail = plain(render.transcript_lines(s3.entries, 66, 5, scroll=0)[-1])
back = plain(render.transcript_lines(s3.entries, 66, 5, scroll=10)[-1])
check("scrolling shows older text", "39" in tail and "29" in back, f"{tail!r} / {back!r}")

print()

print("\n-- the tuning screen repeats the last note --")
rows = render.tune_rows({"note": "search up: carrier 1500 -> 1832 Hz"}, 66)
joined = "\n".join(rows)
check("the note appears on the screen",
      "search up: carrier 1500 -> 1832 Hz" in joined, joined)
rows = render.tune_rows({}, 66)
check("no note leaves a blank row rather than an error",
      any(r.strip() == "" for r in rows), rows)
check("a long note is truncated to the width",
      all(len(r) <= 66 for r in render.tune_rows({"note": "x" * 200}, 66)),
      [len(r) for r in render.tune_rows({"note": "x" * 200}, 66)])

sys.exit(report())
