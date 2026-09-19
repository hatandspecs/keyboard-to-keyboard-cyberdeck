"""Menus render inside every grid the panel can produce."""
import menus, render
from render import plain
from fldigi_client import Fldigi

FAIL = []
def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"\n          {detail}"))
    if not cond: FAIL.append(name)

GRIDS = [(66, 20), (80, 24), (50, 15), (100, 30)]

print("-- every menu fits every grid --")
for name, menu in [("root", menus.ROOT), ("display", menus.DISPLAY),
                   ("tuning", menus.tuning_menu(True, False, 5.0, True, True)),
                   ("radio", menus.RADIO),
                   ("system", menus.SYSTEM),
                   ("station", menus.station_menu({"CALLSIGN": "KD3CCO", "NAME": "Don"})),
                   ("mode", menus.mode_menu("BPSK31"))]:
    for w, h in GRIDS:
        lines = menus.render(menu, w, h)
        too_wide = [plain(l) for l in lines if len(plain(l)) > w]
        check(f"{name} at {w}x{h}", len(lines) == h and not too_wide,
              f"lines={len(lines)} over={too_wide[:1]}")

print("\n-- the mode menu marks the mode in use --")
m = menus.mode_menu("RTTY")
labels = [lbl for _, lbl in m["items"]]
check("current mode flagged", any(l.startswith("RTTY") and l.endswith("<") for l in labels), labels[:5])
check("'more' offered", any("more" in l for l in labels))

print("\n-- the conversational subset of a real fldigi modem list --")
f = Fldigi()
names = f.modem_names()
kb = menus.keyboard_modes(names)
check("fldigi answered", len(names) > 100, len(names))
check("subset is smaller than the whole", 0 < len(kb) < len(names), f"{len(kb)} of {len(names)}")
check("every tier-1 mode exists in fldigi", all(n in names for _, n in menus.MODE_TIER1),
      [n for _, n in menus.MODE_TIER1 if n not in names])
print(f"    {len(kb)} conversational modems, first few: {', '.join(kb[:6])}")

print("\n-- paging the long list --")
for w, h in GRIDS:
    menu, page, pages, keymap = menus.paged_menu("ALL MODES", kb, 0, w, h)
    lines = menus.render(menu, w, h)
    over = [plain(l) for l in lines if len(plain(l)) > w]
    check(f"page 1 of {pages} at {w}x{h}", len(lines) == h and not over, over[:1])
    check(f"  keys map to modems at {w}", all(v in kb for v in keymap.values()))

menu, page, pages, keymap = menus.paged_menu("ALL MODES", kb, 99, 66, 20)
check("page number clamped to the last page", page == pages - 1, f"{page}/{pages}")

print("\n-- a two-column page at 66x20 --")
menu, *_ = menus.paged_menu("ALL MODES", kb, 0, 66, 20)
for l in menus.render(menu, 66, 20):
    t = plain(l)
    if t.strip(): print(f"    |{t}|")

print()
print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
