"""Layout at every grid the panel can produce (design_doc.md §3.3)."""
import time, render
from render import plain
from session import Session

FAIL = []
def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"\n          {detail}"))
    if not cond: FAIL.append(name)

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
s.receive("KD3CCO de W3TM  good copy, 599 here in State College. "
          "rig is an FTX-1 running 20 watts into a vertical.\n")
for c in "W3TM de KD3CCO  copy 100 percent": s.type(c)
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
lines, (row, col) = render.compose_lines("W3TM de KD3CCO  all the fldigi modes", "[RX 36]", 66, 2)
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

print("\n-- scroll back through history --")
s3 = Session(callsign="KD3CCO")
for i in range(40): s3.note(f"line {i}")
tail = plain(render.transcript_lines(s3.entries, 66, 5, scroll=0)[-1])
back = plain(render.transcript_lines(s3.entries, 66, 5, scroll=10)[-1])
check("scrolling shows older text", "39" in tail and "29" in back, f"{tail!r} / {back!r}")

print()
print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
