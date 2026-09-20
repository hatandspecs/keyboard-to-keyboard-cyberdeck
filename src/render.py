"""Turning a Session into lines of text.

Kept free of curses so the layout can be tested at any width without a
terminal, which matters because the grid is not fixed: the 800x480 panel gives
66x20 at the proposed 12x24 console font, 80x24 at 10x20, and 50x15 at 16x32
(docs/design_doc.md §3.3). Everything here adapts to the width it is given rather
than assuming one.

A rendered line is a list of (text, kind) segments. The kind names an
appearance — "dim", "bright", "reverse" — and the curses layer decides what
that means in the current color scheme. Nothing here knows about color.
"""

import time

TIME_W = 5          # "2114Z"
WHO_W = 7           # callsign column, left-justified

# Status fields in the order they are dropped when the screen is too narrow.
# Callsign, transmit state and the clock are never dropped: they are the three
# a glance is for.
_DROP_ORDER = ("imd", "sideband", "snr", "carrier", "freq", "mode")


def _wrap(text, width):
    """Wrap on spaces, breaking long runs rather than overflowing.

    Received text can contain a hundred characters with no space in it when a
    signal is marginal, and a line that overflows the screen is worse than one
    broken mid-word.
    """
    if width <= 0:
        return [""]
    lines, line = [], ""
    for word in text.split(" "):
        while len(word) > width:
            if line:
                lines.append(line); line = ""
            lines.append(word[:width]); word = word[width:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= width:
            line += " " + word
        else:
            lines.append(line); line = word
    lines.append(line)
    return lines


def entry_lines(entry, width, timestamps=True, utc=True):
    """One transcript entry as rendered lines."""
    gutter = (TIME_W + 1 if timestamps else 0) + WHO_W + 1
    body_w = max(8, width - gutter - 1)
    stamp = ""
    if timestamps:
        t = time.gmtime(entry.when) if utc else time.localtime(entry.when)
        stamp = time.strftime("%H%M", t) + "Z"

    out = []
    for i, text in enumerate(_wrap(entry.text, body_w)):
        segs = [(" ", "dim")]
        if timestamps:
            segs.append(((stamp if i == 0 else "").ljust(TIME_W) + " ", "dim"))
        segs.append(((entry.who if i == 0 else "").ljust(WHO_W) + " ", "dim"))
        segs.append((text, "note" if entry.who == "--" else "bright"))
        out.append(segs)
    return out


def transcript_lines(entries, width, height, timestamps=True, scroll=0):
    """The last `height` lines of the transcript, oldest first.

    `scroll` counts lines back from the live tail, for PgUp review.
    """
    rendered = []
    for entry in entries:
        rendered.extend(entry_lines(entry, width, timestamps))
    if height <= 0:
        return []
    end = len(rendered) - scroll
    end = max(0, min(end, len(rendered)))
    start = max(0, end - height)
    window = rendered[start:end]
    return window + [[("", "bright")]] * (height - len(window))


def frequency(hz):
    """A VFO reading at the radio's own resolution: 14.070.589

    Megahertz, kilohertz, hertz, grouped with dots. Digital work is done in
    tens of hertz inside a 31 Hz-wide signal, so rounding to three decimals
    throws away the part of the number that matters when comparing the deck's
    reading against the radio's display.
    """
    try:
        hz = int(round(float(hz)))
    except (TypeError, ValueError):
        return ""
    if hz <= 0:
        return ""
    mhz, rest = divmod(hz, 1_000_000)
    khz, rest = divmod(rest, 1_000)
    return f"{mhz}.{khz:03d}.{rest:03d}"


# Nominal bandwidths for modes whose name defines the number, used when
# fldigi reports 0. It reports a figure only where bandwidth is a settable
# parameter of the modem — Hell, for instance — and 0 for everything fixed,
# which is most of what gets used. Displaying that 0 says BPSK31 is zero hertz
# wide, which is worse than saying nothing.
_NOMINAL_BW = {
    "BPSK31": 31, "QPSK31": 31, "PSK31": 31,
    "BPSK63": 63, "QPSK63": 63, "PSK63": 63,
    "BPSK125": 125, "PSK125": 125,
}


def mode_bandwidth(name, reported=0):
    """Signal bandwidth in Hz as a string, or an em dash when unknown.

    Only figures that are definitional are asserted: the PSK family from its
    symbol rate, and Olivia and Contestia from the name itself, where the
    second number IS the bandwidth. Anything else falls back to whatever
    fldigi reports, and to nothing at all when it reports zero.
    """
    try:
        reported = int(reported)
    except (TypeError, ValueError):
        reported = 0
    if reported > 0:
        return f"{reported} Hz"

    name = (name or "").upper()
    if name in _NOMINAL_BW:
        return f"{_NOMINAL_BW[name]} Hz"

    # OLIVIA-8/250, CONTESTIA-8/500: tones/bandwidth.
    if "/" in name and name.split("-")[0] in ("OLIVIA", "CONTESTIA"):
        tail = name.rsplit("/", 1)[-1]
        if tail.isdigit():
            return f"{tail} Hz"
    return "\u2014"


# The tuning screen's readouts and key hints. These live here, not in the
# terminal, so that the documentation screenshots render from the same source
# as the panel — the hand-copied version in tools/capture_screens.py drifted
# every time a control was added, and the published screenshot quietly stopped
# matching the deck.
TUNE_HINTS = (
    "  \u2190 \u2192  carrier \u00b110 Hz      \u2191 \u2193  search signal",
    "  , .  VFO \u00b1100 Hz         < >  VFO \u00b11 kHz",
    "  a AFC  s sql  r RSID  x TXID  v REV   F2/Esc back",
)


def tune_rows(fields, width):
    """The body of the F2 screen as plain strings.

    `fields` carries already-formatted values so this stays free of fldigi:
    freq, rig_mode, carrier, width, snr, imd, quality, afc, squelch,
    squelch_level, rsid, txid, reverse.
    """
    def onoff(v, pad=True):
        return ("on " if pad else "on") if v else "off"

    q = float(fields.get("quality", 0) or 0)
    bar_w = max(10, width - 22)
    filled = int(bar_w * min(max(q, 0), 100) / 100)
    return [
        f"  rig      {fields.get('freq', '')}  {fields.get('rig_mode', '')}",
        f"  carrier  {fields.get('carrier', 0)} Hz        width  "
        f"{fields.get('width', '')}",
        f"  S/N      {(fields.get('snr') or '').strip()}",
        f"  IMD      {(fields.get('imd') or '').strip()}",
        "",
        f"  quality  {'\u2588' * filled}{'\u2591' * (bar_w - filled)}  {q:.0f}",
        "",
        f"  AFC {onoff(fields.get('afc'))}  squelch {onoff(fields.get('squelch'))}"
        f" ({float(fields.get('squelch_level', 0)):.0f})"
        f"  RSID {onoff(fields.get('rsid'))}"
        f"  TXID {onoff(fields.get('txid'))}"
        f"  REV {onoff(fields.get('reverse'), pad=False)}",
    ]


def status_line(fields, width):
    """The top line: one row, always visible, reverse video.

    Fields are dropped from the least useful end when the width will not take
    them all, so a 50-column deck still shows callsign, state and clock.
    """
    parts = {
        "call":     fields.get("call", ""),
        "freq":     fields.get("freq", ""),
        "sideband": fields.get("sideband", ""),
        "mode":     fields.get("mode", ""),
        "carrier":  fields.get("carrier", ""),
        "snr":      fields.get("snr", ""),
        "imd":      fields.get("imd", ""),
    }
    order = ["call", "freq", "sideband", "mode", "carrier", "snr", "imd"]
    shown = [k for k in order if parts[k]]
    clock = fields.get("clock", "")
    state = fields.get("state", "")

    def build(keys):
        left = "  ".join(parts[k] for k in keys)
        right = f"{state}  {clock}".strip()
        pad = width - len(left) - len(right) - 2
        if pad < 1:
            return None
        return " " + left + " " * pad + right + " "

    for _ in range(len(_DROP_ORDER) + 1):
        line = build(shown)
        if line is not None:
            return [(line, "reverse")]
        for candidate in _DROP_ORDER:
            if candidate in shown:
                shown.remove(candidate)
                break
        else:
            break
    # Nothing fits: show the irreducible minimum, truncated.
    return [((" " + parts["call"] + " " + state).ljust(width)[:width], "reverse")]


def compose_lines(text, indicator, width, height, cursor=None):
    """The bottom region: what is being typed, with the buffer indicator
    right-aligned on the last line. Returns lines and the cursor position
    within them as (row, col).

    `cursor` is an index into `text`; None means the end, which is where it
    sits unless the line is being edited.
    """
    body_w = max(8, width - 2)
    wrapped = _wrap(text, body_w) or [""]
    shown = wrapped[-height:] if height else wrapped

    if cursor is None:
        cursor = len(text)
    cursor = max(0, min(len(text), cursor))
    # Walk the wrapped lines counting characters until the cursor index is
    # reached, so the caret lands where the character actually is rather than
    # at the end of the text.
    remaining, row, col = cursor, 0, 0
    for i, line in enumerate(wrapped):
        if remaining <= len(line):
            row, col = i, remaining
            break
        remaining -= len(line)
        row, col = i, len(line)
    else:
        row, col = len(wrapped) - 1, len(wrapped[-1])

    hidden = len(wrapped) - len(shown)
    cursor_row = max(0, row - hidden)
    cursor_col = 1 + col
    wrapped = shown

    out = []
    for i, line in enumerate(wrapped):
        if i == len(wrapped) - 1:
            pad = width - len(line) - len(indicator) - 2
            if pad >= 1:
                out.append([(" " + line + " " * pad, "bright"), (indicator + " ", "dim")])
            else:
                out.append([(" " + line, "bright")])
        else:
            out.append([(" " + line, "bright")])
    while len(out) < height:
        out.append([("", "bright")])
    return out, (cursor_row, min(cursor_col, width - 1))


def rule(width):
    return [("─" * width, "dim")]


def plain(segments):
    """A rendered line as a plain string, for tests."""
    return "".join(text for text, _ in segments)


# Key hints, longest first. The deck's grid is 66 columns at the proposed font
# and 50 at the largest one, so the line has to shed bindings rather than be
# truncated mid-word — a hint that reads "^C abor" is worse than no hint.
_HINT_TIERS = (
    " F1 menu  F2 tune  F5/F6 carrier  F7/F8 search  ^T over  ^K hand"
    "  ^C abort",
    " F1 menu  F2 tune  F5-F8 tune  ^T over  ^K hand  ^C abort",
    " F1 menu  F2 tune  F5-F8 tune  ^T over  ^K hand",
    " F1 menu  F2 tune  F3 mode  F4 color  ^T over  ^K hand",
    " F2 tune  F3 mode  F4 color  ^T over  ^K hand",
    " F2 tune  ^T over  ^K hand  ^C abort",
    " ^T over  ^K hand  ^C abort",
    " ^T/^K/^C",
)


def hint_line(width):
    for tier in _HINT_TIERS:
        if len(tier) <= width:
            return [(tier, "dim")]
    return [(_HINT_TIERS[-1][:width], "dim")]
