"""The four monochrome schemes (design_doc.md §5.7).

Each is one hue on black, with a dim variant for the timestamp and callsign
columns. Monochrome means one hue, not one intensity.

Two paths to the color, because the deck and the development machine are not
the same thing:

* **A Linux virtual console** takes `OSC P` escape sequences, which redefine
  palette entries outright. That is what allows a true amber and a true Matrix
  green rather than the ANSI approximations of yellow and green, and it is why
  switching schemes costs four escape sequences rather than a repaint.
* **Anything else** — a terminal emulator over SSH, which is where this gets
  developed — falls back to the nearest of the eight ANSI colors. Deckard
  becomes yellow and loses its amber, which is a development compromise and
  not what the panel will show.
"""

import curses
import os

SCHEMES = {
    "matrix":  {"name": "Matrix",  "bright": "00FF41", "dim": "00A62A", "ansi": curses.COLOR_GREEN},
    "deckard": {"name": "Deckard", "bright": "FFB000", "dim": "B27B00", "ansi": curses.COLOR_YELLOW},
    "hal":     {"name": "Hal",     "bright": "FF3B30", "dim": "A62018", "ansi": curses.COLOR_RED},
    "tron":    {"name": "Tron",    "bright": "00D9FF", "dim": "0089A8", "ansi": curses.COLOR_CYAN},
}
ORDER = ("matrix", "deckard", "hal", "tron")

# Which palette entries to redefine on a Linux console.
#
# These are NOT free-choice slots. A curses color pair on the Linux console can
# only name entries 0-7 — entries 8-15 are reachable for a foreground only via
# A_BOLD, which the console implements by adding 8, and not at all for a
# background. So the two entries the console will actually land on for a given
# scheme are:
#
#     dim text      -> the ANSI index itself          (e.g. yellow = 3)
#     bright text   -> that index + 8, via A_BOLD     (e.g. 11)
#
# An earlier version redefined entries 8 and 9 instead, on the reasoning that
# nothing else uses them. Nothing else did — including this program, which
# drew with the ANSI index and never referenced them. Every scheme rendered as
# its ANSI approximation, and Deckard's amber came out as yellow.
def _slots(ansi):
    """(dim entry, bright entry) for an ANSI color index."""
    return ansi, ansi + 8

PAIR_BRIGHT = 1
PAIR_DIM = 2
PAIR_REVERSE = 3


def on_linux_console():
    """True on a bare virtual console, where the palette can be redefined."""
    return os.environ.get("TERM", "") == "linux"


def _osc_palette(slot, rrggbb):
    return f"\033]P{slot:X}{rrggbb}"


# True when the color pairs address the redefined palette slots directly, and
# the intensity attributes must therefore be left off. See apply().
_direct_palette = False


def apply(scheme_key):
    """Set up curses color pairs for a scheme, redefining the console
    palette where that is possible. Returns the scheme dict."""
    global _direct_palette
    scheme = SCHEMES[scheme_key]
    _direct_palette = False

    if on_linux_console():
        dim_slot, bright_slot = _slots(scheme["ansi"])
        try:
            out = (_osc_palette(bright_slot, scheme["bright"])
                   + _osc_palette(dim_slot, scheme["dim"]))
            os.write(1, out.encode("ascii"))
            _direct_palette = True
        except OSError:
            pass

    # The pair always names the ANSI index, which is all a background can be
    # and all an 8-color terminfo will accept. On a console the palette behind
    # that index now holds the scheme's real hex values; elsewhere it is the
    # terminal's own approximation.
    try:
        curses.init_pair(PAIR_BRIGHT, scheme["ansi"], curses.COLOR_BLACK)
        curses.init_pair(PAIR_DIM, scheme["ansi"], curses.COLOR_BLACK)
        # Black ON the hue, defined outright rather than asking the terminal
        # to swap a normal pair: see attr(). The bar takes the dim entry,
        # because a background cannot reach the bright one — black on deep
        # amber, rather than black on full-brightness amber.
        curses.init_pair(PAIR_REVERSE, curses.COLOR_BLACK, scheme["ansi"])
    except curses.error:
        pass
    return scheme


def attr(kind):
    """Map a render kind to a curses attribute.

    A_BOLD is what selects the bright half of a scheme, on a console and off
    it. On a console it moves the foreground to the redefined `ansi + 8` entry
    holding the scheme's bright hex value; elsewhere it asks the terminal for
    its own bright variant. Either way it is required, not optional.

    A_DIM is dropped on a console: the Linux console ignores it, and the dim
    hue is already carried by the base palette entry.
    """
    if kind == "reverse":
        # No A_REVERSE and no A_BOLD. The pair is already black-on-hue, and
        # asking for both was what made the status bar unreadable: with
        # A_REVERSE the console swaps foreground and background, then applies
        # A_BOLD's intensity to what is now the background, leaving text the
        # same hue as the bar it sits on. A filled bar needs black text in it,
        # so define that directly and let no attribute negotiate it away.
        return curses.color_pair(PAIR_REVERSE)
    if kind in ("dim", "note"):
        return curses.color_pair(PAIR_DIM) | (0 if _direct_palette else curses.A_DIM)
    return curses.color_pair(PAIR_BRIGHT) | curses.A_BOLD


def cycle(current):
    return ORDER[(ORDER.index(current) + 1) % len(ORDER)]
