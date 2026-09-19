"""Menu navigation, driven through a real pty, with fldigi checked afterwards."""
from test_screen import run, show
from fldigi_client import Fldigi

F1, F2, F3, F4 = "\x1bOP", "\x1bOQ", "\x1bOR", "\x1bOS"
FAIL = []
def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"\n          {detail}"))
    if not cond: FAIL.append(name)

f = Fldigi()
f.set_modem("BPSK31")

body = show("F1 root menu", run(keys=[F1]))
check("root menu opens", "MENU" in body)
check("its items are listed", all(w in body for w in ("Mode", "Tuning", "Radio", "Display", "Station", "System")))

body = show("F1 then 4 -> Display", run(keys=[F1, "4"]))
check("display menu reached", "DISPLAY" in body)
check("all four schemes offered", all(w in body for w in ("Matrix", "Deckard", "Hal", "Tron")))

body = show("F3 mode picker", run(keys=[F3]))
check("mode menu opens", "MODE" in body)
check("current mode is marked", "BPSK31  <" in body, [l for l in body.splitlines() if "BPSK31" in l])
check("'more modes' offered", "more modes" in body)

body = show("F3 then m -> the full list", run(keys=[F3, "m"]))
check("paged list reached", "ALL MODES" in body and "page 1/" in body)
check("single-key selection shown", " a " in body and " b " in body)

print("\n-- selecting RTTY actually changes fldigi's modem --")
run(keys=[F3, "4"], settle=1.5)
after = f.modem()
check("fldigi is now on RTTY", after == "RTTY", after)

# Each run starts a fresh Deck, which applies DEFAULT_MODE from the config on
# startup — so a mode set in one run is deliberately overridden in the next.
# The marking has to be checked inside a single session: pick RTTY, reopen the
# menu, and look.
body = show("select RTTY then reopen the menu, one session",
            run(keys=[F3, "4", F3]))
check("RTTY marked as current", "RTTY  <" in body,
      [l for l in body.splitlines() if "RTTY" in l])
f.set_modem("BPSK31")

print("\n-- the radio menu sets the VFO --")
before = f.frequency()
run(keys=[F1, "3", "1"], settle=1.5)          # menu -> Radio -> 14.070
after = f.frequency()
check("VFO moved to 14.070", abs(after - 14_070_000) < 1000, f"{before} -> {after}")

print()
print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
