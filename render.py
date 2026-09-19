"""Turning a Session into lines of text.

Kept free of curses so the layout can be tested at any width without a
terminal, which matters because the grid is not fixed: the 800x480 panel gives
66x20 at the proposed 12x24 console font, 80x24 at 10x20, and 50x15 at 16x32
(design_doc.md §3.3). Everything here adapts to the width it is given rather
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


def compose_lines(text, indicator, width, height):
    """The bottom region: what is being typed, with the buffer indicator
    right-aligned on the last line. Returns lines and the cursor position
    within them as (row, col)."""
    body_w = max(8, width - 2)
    wrapped = _wrap(text, body_w) or [""]
    wrapped = wrapped[-height:] if height else wrapped
    cursor_row = len(wrapped) - 1
    cursor_col = 1 + len(wrapped[-1])

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
    " F1 menu  F2 tune  F3 mode  F4 color  ^T over  ^K hand  ^C abort",
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
