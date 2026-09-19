"""Full-screen menus, selected by a single key (design_doc.md §5.6).

No pointer, no cursor to move, no nesting deeper than two: a menu is a list of
labeled keys and pressing one does the thing. That is the fastest interface
on a keyboard and the only sane one on a console with no mouse.

The structure is data and the rendering is a pure function, so both can be
tested at 50, 66, 80 and 100 columns without a terminal. What each item *does*
is wired up in cyberdeck.py, because only that knows about fldigi.
"""

# The curated first tier of conversational modems (§6). fldigi offers 169, of
# which 64 are keyboard modes; putting all of them on one screen makes the
# screen the problem. Everything else is reachable under "more".
MODE_TIER1 = [
    ("1", "BPSK31"),
    ("2", "BPSK63"),
    ("3", "QPSK31"),
    ("4", "RTTY"),
    ("5", "OLIVIA-8/250"),
    ("6", "OLIVIA-8/500"),
    ("7", "MFSK16"),
    ("8", "THOR22"),
    ("9", "CONTESTIA"),
    ("0", "DOMEX8"),
    ("h", "FELDHELL"),
]

# Which modems count as conversational, for the "more" list.
_KEYBOARD_FAMILIES = ("BPSK", "QPSK", "PSK", "RTTY", "OLIVIA", "MFSK",
                      "CONTESTIA", "THOR", "DOMEX", "FELDHELL", "HELL")

PAGE_KEYS = "abcdefghijklmnopqrstuvwxyz"


def keyboard_modes(all_names):
    """The conversational subset of fldigi's modem list, in family order."""
    out = []
    for family in _KEYBOARD_FAMILIES:
        for name in all_names:
            if name.upper().startswith(family) and name not in out:
                out.append(name)
    return out


ROOT = {
    "title": "MENU",
    "items": [
        ("1", "Mode"),
        ("2", "Tuning"),
        ("3", "Radio"),
        ("4", "Display"),
        ("5", "Station"),
        ("6", "System"),
    ],
    "footer": "Esc back to the conversation   ↑↓ move   Enter select",
}

DISPLAY = {
    "title": "DISPLAY",
    "items": [
        ("1", "Color: Matrix   green"),
        ("2", "Color: Deckard  amber"),
        ("3", "Color: Hal      red"),
        ("4", "Color: Tron     cyan"),
        ("t", "Timestamps on/off"),
    ],
    "footer": "Esc back   ↑↓ move   Enter select",
}

def tuning_menu(afc, squelch, level, rsid, txid):
    """Tuning options with their current state shown.

    The static version of this menu gave no feedback: pressing `s` toggled
    the squelch and the screen did not change, which reads as a dead key.
    """
    def onoff(v):
        return "ON " if v else "off"

    return {
        "title": "TUNING",
        "items": [
            ("a", f"AFC         {onoff(afc)}"),
            ("s", f"Squelch     {onoff(squelch)}"),
            ("+", f"Squelch level up       ({level:.0f})"),
            ("-", f"Squelch level down     ({level:.0f})"),
            ("r", f"RSID        {onoff(rsid)}   follow others' identifiers"),
            ("x", f"TXID        {onoff(txid)}   send one before our overs"),
            ("c", "Park carrier at the configured offset"),
        ],
        "footer": "Esc back   ↑↓ move   Enter select   F2 live tuning",
    }

RADIO = {
    "title": "RADIO",
    "items": [
        ("1", "14.070  20 m"),
        ("2", "7.070   40 m"),
        ("3", "3.580   80 m"),
        ("4", "10.142  30 m"),
        ("5", "21.070  15 m"),
        ("6", "28.120  10 m"),
    ],
    "footer": "Esc back   ↑↓ move   Enter select   sets VFO and mode",
}

BAND_FREQUENCIES = {
    "1": 14_070_000, "2": 7_070_000, "3": 3_580_000,
    "4": 10_142_000, "5": 21_070_000, "6": 28_120_000,
}

SYSTEM = {
    "title": "SYSTEM",
    "items": [
        ("i", "Transmit inhibit on/off"),
        ("c", "Clear the transcript"),
        ("q", "Quit"),
    ],
    "footer": "Esc back   ↑↓ move   Enter select",
}


def station_menu(settings):
    """Read-only: what this station calls itself."""
    return {
        "title": "STATION",
        "items": [
            (" ", f"Callsign  {settings.get('CALLSIGN') or '(not set)'}"),
            (" ", f"Name      {settings.get('NAME') or '-'}"),
            (" ", f"QTH       {settings.get('QTH') or '-'}"),
            (" ", f"Locator   {settings.get('LOCATOR') or '-'}"),
        ],
        "footer": "Esc  back      edit these in cyberdeck.conf",
    }


def mode_menu(current, extra=None):
    items = list(MODE_TIER1)
    if extra:
        items = items + extra
    items = [(k, (f"{n}  <" if n == current else n)) for k, n in items]
    items.append(("m", "more modes ..."))
    return {"title": "MODE", "items": items,
            "footer": "Esc back   ↑↓ move   Enter select   < marks the mode in use"}


def paged_menu(title, names, page, width, height):
    """A long list broken into single-key pages.

    Two columns where the width allows, because 64 modems in one column is
    four pages of scrolling and one of reading.
    """
    per_page = max(1, min(len(PAGE_KEYS), (height - 6) * (2 if width >= 60 else 1)))
    pages = max(1, (len(names) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    chunk = names[page * per_page:(page + 1) * per_page]
    items = [(PAGE_KEYS[i], name) for i, name in enumerate(chunk)]
    return {
        "title": f"{title}  page {page + 1}/{pages}",
        "items": items,
        "footer": "Esc  back      PgUp/PgDn  more",
    }, page, pages, {PAGE_KEYS[i]: n for i, n in enumerate(chunk)}


def selectable(menu):
    """Indices of items that can actually be chosen.

    The station menu lists read-only fields keyed with a space; arrow-key
    navigation has to step over them rather than land on a row that does
    nothing when Enter is pressed.
    """
    return [i for i, (key, _) in enumerate(menu["items"]) if key.strip()]


def render(menu, width, height, selected=None):
    """A menu as rendered lines: list of (text, kind) segments.

    `selected` is an index into menu["items"]; that row is drawn in reverse
    video so the arrow keys have something to point at.
    """
    lines = [[(" " + menu["title"][:width - 2].ljust(width - 1), "reverse")],
             [("", "bright")]]

    items = menu["items"]
    two_col = width >= 60 and len(items) > (height - 6)
    if two_col:
        half = (len(items) + 1) // 2
        col_w = (width - 3) // 2
        for i in range(half):
            left = items[i]
            right = items[i + half] if i + half < len(items) else None
            lk = "reverse" if selected == i else "dim"
            segs = [("  ", "dim"), (f"{left[0]} ", "bright"),
                    (left[1][:col_w - 4].ljust(col_w - 2), lk)]
            if right:
                rk = "reverse" if selected == i + half else "dim"
                segs += [(f"{right[0]} ", "bright"), (right[1][:col_w - 4], rk)]
            lines.append(segs)
    else:
        for i, (key, label) in enumerate(items):
            kind = "reverse" if selected == i else "dim"
            lines.append([("   ", "dim"), (f"{key}  ", "bright"),
                          (label[:width - 8], kind)])

    while len(lines) < height - 2:
        lines.append([("", "bright")])
    lines = lines[:height - 2]
    lines.append([("─" * width, "dim")])
    lines.append([(" " + menu["footer"][:width - 2], "dim")])
    return lines[:height]
