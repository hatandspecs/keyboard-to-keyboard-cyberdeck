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

# Palette slots redefined on a Linux console. 9 and 8 are bright/dim entries
# that nothing else in a bare console depends on.
_SLOT_BRIGHT = 9
_SLOT_DIM = 8

PAIR_BRIGHT = 1
PAIR_DIM = 2
PAIR_REVERSE = 3


def on_linux_console():
    """True on a bare virtual console, where the palette can be redefined."""
    return os.environ.get("TERM", "") == "linux"


def _osc_palette(slot, rrggbb):
    return f"\033]P{slot:X}{rrggbb}"


def apply(scheme_key):
    """Set up curses color pairs for a scheme, redefining the console
    palette where that is possible. Returns the scheme dict."""
    scheme = SCHEMES[scheme_key]
    if on_linux_console():
        try:
            out = (_osc_palette(_SLOT_BRIGHT, scheme["bright"])
                   + _osc_palette(_SLOT_DIM, scheme["dim"]))
            os.write(1, out.encode("ascii"))
        except OSError:
            pass
    try:
        curses.init_pair(PAIR_BRIGHT, scheme["ansi"], curses.COLOR_BLACK)
        curses.init_pair(PAIR_DIM, scheme["ansi"], curses.COLOR_BLACK)
        curses.init_pair(PAIR_REVERSE, scheme["ansi"], curses.COLOR_BLACK)
    except curses.error:
        pass
    return scheme


def attr(kind):
    """Map a render kind to a curses attribute."""
    if kind == "reverse":
        return curses.color_pair(PAIR_REVERSE) | curses.A_REVERSE | curses.A_BOLD
    if kind == "dim":
        return curses.color_pair(PAIR_DIM) | curses.A_DIM
    if kind == "note":
        return curses.color_pair(PAIR_DIM) | curses.A_DIM
    return curses.color_pair(PAIR_BRIGHT) | curses.A_BOLD


def cycle(current):
    return ORDER[(ORDER.index(current) + 1) % len(ORDER)]
