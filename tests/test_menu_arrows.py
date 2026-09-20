"""Arrow-key menu navigation and live menu state, driven through a real pty.

The harness runs with TERM=xterm, where keypad(True) puts the terminal into
application cursor mode: Down is \x1bOB, not \x1b[B. The deck itself runs on
the Linux console, where kcud1 is \x1b[B. ncurses resolves both from terminfo;
the test has to send whatever its own TERM specifies.
"""
import os
import sys

# src/ holds the application; tests/ holds this. Both are addressed from the
# project root so a test can be run from anywhere.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT, "src")
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_screen import run, show
from fldigi_client import Fldigi

F1, F3 = "\x1bOP", "\x1bOR"
UP, DOWN, ENTER, ESC = "\x1bOA", "\x1bOB", "\r", "\x1b"
FAIL = []
def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"\n          {detail}"))
    if not cond: FAIL.append(name)

body = show("F1, then Down Down", run(keys=[F1, DOWN, DOWN]))
check("root menu still open after arrows", "MENU" in body)

print("\n-- Down x2 then Enter should reach the third item, Radio --")
body = show("F1 Down Down Enter", run(keys=[F1, DOWN, DOWN, ENTER]))
check("landed on RADIO", "RADIO" in body, body[:400])

print("\n-- Enter on the first item reaches Mode --")
body = show("F1 Enter", run(keys=[F1, ENTER]))
check("landed on MODE", "MODE" in body, body[:400])

print("\n-- Up from the first item wraps to the last, System --")
body = show("F1 Up Enter", run(keys=[F1, UP, ENTER]))
check("wrapped to SYSTEM", "SYSTEM" in body, body[:400])

print("\n-- tuning menu now shows live state --")
body = show("F1 then 2", run(keys=[F1, "2"]))
check("tuning menu shows AFC state", "AFC" in body and ("ON" in body or "off" in body), body[:400])
check("squelch state shown", "Squelch" in body, body[:400])

print("\n-- arrows still leave the single-key shortcuts working --")
body = show("F3 then 4 (RTTY)", run(keys=[F3, "4"], settle=1.5))
check("fldigi on RTTY", Fldigi().modem() == "RTTY", Fldigi().modem())

print("\nALL PASS" if not FAIL else f"\nFAILED: {FAIL}")
