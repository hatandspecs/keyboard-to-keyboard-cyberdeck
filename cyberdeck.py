#!/usr/bin/env python3
"""Keyboard-to-keyboard terminal for fldigi.

The only thing on the screen: a status line, the conversation, and what is
being typed. No window manager, no pointer, nothing to click. fldigi does the
modem work invisibly behind an XML-RPC connection (design_doc.md §4).

Run it over SSH for development; on the deck it runs on tty1 against the
framebuffer, where the colour schemes use the real palette.
"""

import curses
import sys
import time

import colours
import config as configmod
import menus
import render
from fldigi_client import Fldigi
from session import Session, RX, TX

CHAT, TUNE = "chat", "tune"



class Deck:
    def __init__(self, stdscr, settings):
        self.scr = stdscr
        self.cfg = settings
        self.scheme = settings["COLOUR"]
        self.screen = CHAT
        self.scroll = 0
        # Which menu is open, if any, and where in a paged list. A single
        # value rather than a stack: the tree is two deep by design, and
        # Esc from anywhere returns to the conversation.
        self.menu = None
        self.menu_page = 0
        self._page_keys = {}
        self.status_note = ""
        self.fldigi = Fldigi(url=settings["FLDIGI_URL"])
        self.session = Session(
            callsign=settings["CALLSIGN"],
            scrollback=settings["SCROLLBACK"],
            tx_timeout=settings["TX_TIMEOUT"],
        )
        if self.fldigi.connected:
            if settings["DEFAULT_MODE"]:
                self.fldigi.set_modem(settings["DEFAULT_MODE"])
            self.fldigi.set_carrier(settings["DEFAULT_CARRIER"])
            self.session.note(f"fldigi {self.fldigi.version()} — {self.fldigi.modem()} "
                              f"at {self.fldigi.carrier()} Hz")
        else:
            self.session.note("no connection to fldigi — check it is running")

    # -- fldigi ------------------------------------------------------------

    def poll(self):
        text = self.fldigi.poll_rx()
        if text:
            self.session.receive(text)
            self.scroll = 0
        if self.session.tx_timed_out():
            self.fldigi.abort()
            self.session.abort()
            self.session.note(f"transmit timed out after {self.cfg['TX_TIMEOUT']}s")

    # -- rendering ---------------------------------------------------------

    def status_fields(self):
        f = self.fldigi
        freq = f.frequency()
        state = "TX" if self.session.state == TX else "RX"
        if self.session.inhibited:
            state = "INH"
        if not f.connected:
            state = "NO MODEM"
        return {
            "call": self.cfg["CALLSIGN"] or "NO CALL",
            # Three decimals is how a frequency is read aloud and written
            # in a log: 14.070, not 14.07.
            "freq": f"{freq/1e6:.3f}" if freq else "",
            "sideband": f.rig_mode() or "",
            "mode": f.modem(),
            "carrier": f"{f.carrier()}Hz",
            "snr": (f.signal_to_noise() or "").strip(),
            "imd": (f.imd() or "").strip(),
            "state": state,
            "clock": time.strftime("%H%M", time.gmtime()) + "Z",
        }

    def draw(self):
        scr = self.scr
        scr.erase()
        h, w = scr.getmaxyx()
        if h < 8 or w < 30:
            self._put(0, 0, [("terminal too small", "bright")], w)
            scr.refresh()
            return

        if self.menu:
            self._draw_menu(h, w)
        elif self.screen == TUNE:
            self._draw_tune(h, w)
        else:
            self._draw_chat(h, w)
        scr.refresh()

    def _draw_chat(self, h, w):
        compose_h = 2
        body_h = h - 1 - 1 - 1 - compose_h - 1   # status, rule, rule, compose, hints

        self._put(0, 0, render.status_line(self.status_fields(), w), w)
        self._put(1, 0, render.rule(w), w)

        lines = render.transcript_lines(
            self.session.entries, w, body_h,
            timestamps=self.cfg["TIMESTAMPS"] == "yes", scroll=self.scroll)
        for i, line in enumerate(lines):
            self._put(2 + i, 0, line, w)

        rule_row = 2 + body_h
        self._put(rule_row, 0, render.rule(w), w)

        clines, (crow, ccol) = render.compose_lines(
            self.session.compose, self.session.buffer_indicator(), w, compose_h)
        for i, line in enumerate(clines):
            self._put(rule_row + 1 + i, 0, line, w)

        self._put(h - 1, 0, render.hint_line(w), w)
        try:
            self.scr.move(rule_row + 1 + crow, ccol)
        except curses.error:
            pass

    def _draw_tune(self, h, w):
        f = self.fldigi
        self._put(0, 0, render.status_line(
            {**self.status_fields(), "call": "TUNING"}, w), w)
        self._put(1, 0, render.rule(w), w)

        q = f.quality()
        bar_w = max(10, w - 22)
        filled = int(bar_w * min(max(q, 0), 100) / 100)
        rows = [
            f"  rig      {f.frequency()/1e6:.5f}  {f.rig_mode()}",
            f"  carrier  {f.carrier()} Hz        bandwidth  {f.bandwidth()} Hz",
            f"  S/N      {(f.signal_to_noise() or '').strip()}",
            f"  IMD      {(f.imd() or '').strip()}",
            "",
            f"  quality  {'█' * filled}{'░' * (bar_w - filled)}  {q:.0f}",
            "",
            f"  AFC {'on ' if f.afc() else 'off'}   squelch {'on ' if f.squelch() else 'off'}"
            f" ({f.squelch_level():.0f})   RSID {'on ' if f.rsid() else 'off'}"
            f"   TXID {'on' if f.txid() else 'off'}",
        ]
        for i, text in enumerate(rows):
            if 2 + i < h - 4:
                self._put(2 + i, 0, [(text[:w - 1], "bright")], w)

        self._put(h - 4, 0, render.rule(w), w)
        self._put(h - 3, 0, [("  ← →  carrier ±10 Hz      ↑ ↓  search signal"[:w - 1], "dim")], w)
        self._put(h - 2, 0, [("  , .  VFO ±100 Hz         < >  VFO ±1 kHz"[:w - 1], "dim")], w)
        self._put(h - 1, 0, [("  a AFC  s squelch  r RSID  x TXID   F2/Esc back"[:w - 1], "dim")], w)

    def _current_menu(self, w, h):
        f, m = self.fldigi, self.menu
        if m == "root":
            return menus.ROOT
        if m == "display":
            return menus.DISPLAY
        if m == "tuning":
            return menus.TUNING
        if m == "radio":
            return menus.RADIO
        if m == "system":
            return menus.SYSTEM
        if m == "station":
            return menus.station_menu(self.cfg)
        if m == "mode":
            return menus.mode_menu(f.modem())
        if m == "modes_all":
            menu, self.menu_page, _, self._page_keys = menus.paged_menu(
                "ALL MODES", menus.keyboard_modes(f.modem_names()),
                self.menu_page, w, h)
            return menu
        return menus.ROOT

    def _draw_menu(self, h, w):
        for i, line in enumerate(menus.render(self._current_menu(w, h), w, h)):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _put(self, row, col, segments, width):
        x = col
        for text, kind in segments:
            if x >= width:
                break
            chunk = text[:width - x]
            try:
                self.scr.addstr(row, x, chunk, colours.attr(kind))
            except curses.error:
                pass
            x += len(chunk)

    # -- keyboard ----------------------------------------------------------

    def handle(self, ch):
        """Returns False to quit."""
        if ch == -1:
            return True

        if self.menu:
            return self._handle_menu(ch)

        if self.screen == TUNE:
            return self._handle_tune(ch)

        if ch == curses.KEY_F1:
            self._open_menu("root")
        elif ch == curses.KEY_F3:
            self._open_menu("mode")
        elif ch == curses.KEY_F2:
            self.screen = TUNE
        elif ch == curses.KEY_F4:
            self.scheme = colours.cycle(self.scheme)
            colours.apply(self.scheme)
            self.session.note(f"colour: {colours.SCHEMES[self.scheme]['name']}")
        elif ch == 20:                       # Ctrl-T
            text = self.session.start_over()
            if text is not None:
                self.fldigi.start_over(text)
        elif ch == 11:                       # Ctrl-K
            if self.session.hand_back():
                self.fldigi.hand_back()
        elif ch == 3:                        # Ctrl-C
            self.fldigi.abort()
            self.session.abort()
        elif ch == 12:                       # Ctrl-L
            self.scr.clearok(True)
        elif ch == 9:                        # Ctrl-I: inhibit toggle
            self.session.inhibit(not self.session.inhibited)
            self.fldigi.receive_only(self.session.inhibited)
        elif ch == curses.KEY_PPAGE:
            self.scroll += 5
        elif ch == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - 5)
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.session.backspace()
        elif ch in (10, 13):
            self._typed("\n")
        elif 32 <= ch < 127:
            self._typed(chr(ch))
        elif ch == 17:                       # Ctrl-Q quits
            return False
        return True

    def _open_menu(self, which):
        self.menu = which
        self.menu_page = 0

    def _close_menu(self):
        self.menu = None
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _handle_menu(self, ch):
        f, m = self.fldigi, self.menu
        key = chr(ch) if 32 <= ch < 127 else ""

        if ch == 27:                                   # Esc
            self._close_menu() if m in ("root",) else self._open_menu("root")
            if m == "root":
                return True
            return True
        if ch == 17:                                   # Ctrl-Q
            return False
        if ch == curses.KEY_PPAGE and m == "modes_all":
            self.menu_page = max(0, self.menu_page - 1); return True
        if ch == curses.KEY_NPAGE and m == "modes_all":
            self.menu_page += 1; return True

        if m == "root":
            dest = {"1": "mode", "2": "tuning", "3": "radio",
                    "4": "display", "5": "station", "6": "system"}.get(key)
            if dest:
                self._open_menu(dest)
            return True

        if m == "mode":
            if key == "m":
                self._open_menu("modes_all"); return True
            for k, name in menus.MODE_TIER1:
                if key == k:
                    self._set_mode(name)
                    return True
            return True

        if m == "modes_all":
            name = self._page_keys.get(key)
            if name:
                self._set_mode(name)
            return True

        if m == "display":
            scheme = {"1": "matrix", "2": "deckard", "3": "hal", "4": "tron"}.get(key)
            if scheme:
                self.scheme = scheme
                colours.apply(scheme)
                self.session.note(f"colour: {colours.SCHEMES[scheme]['name']}")
                self._close_menu()
            elif key == "t":
                self.cfg["TIMESTAMPS"] = "no" if self.cfg["TIMESTAMPS"] == "yes" else "yes"
                self.session.note(f"timestamps {self.cfg['TIMESTAMPS']}")
                self._close_menu()
            return True

        if m == "tuning":
            if key == "a":
                f.set_afc(not f.afc())
            elif key == "s":
                f.set_squelch(not f.squelch())
            elif key == "r":
                f.set_rsid(not f.rsid())
            elif key == "x":
                f.set_txid(not f.txid())
            elif key == "+":
                f.set_squelch_level(min(100.0, f.squelch_level() + 5))
            elif key == "-":
                f.set_squelch_level(max(0.0, f.squelch_level() - 5))
            elif key == "c":
                f.set_carrier(self.cfg["DEFAULT_CARRIER"])
                self.session.note(f"carrier parked at {self.cfg['DEFAULT_CARRIER']} Hz")
                self._close_menu()
            return True

        if m == "radio":
            hz = menus.BAND_FREQUENCIES.get(key)
            if hz:
                f.set_frequency(hz)
                self.session.note(f"VFO set to {hz/1e6:.3f}")
                self._close_menu()
            return True

        if m == "system":
            if key == "i":
                self.session.inhibit(not self.session.inhibited)
                f.receive_only(self.session.inhibited)
                self._close_menu()
            elif key == "c":
                self.session.entries.clear()
                f.clear_rx()
                self.session.note("transcript cleared")
                self._close_menu()
            elif key == "q":
                return False
            return True

        return True

    def _set_mode(self, name):
        self.fldigi.set_modem(name)
        self.session.note(f"mode changed to {self.fldigi.modem()}")
        self._close_menu()

    def _typed(self, char):
        out = self.session.type(char)
        if out:
            self.fldigi.send_more(out)
        self.scroll = 0

    def _handle_tune(self, ch):
        f = self.fldigi
        if ch in (curses.KEY_F2, 27):
            self.screen = CHAT
        elif ch == curses.KEY_LEFT:
            f.nudge_carrier(-10)
        elif ch == curses.KEY_RIGHT:
            f.nudge_carrier(10)
        elif ch == curses.KEY_UP:
            f.search_up()
        elif ch == curses.KEY_DOWN:
            f.search_down()
        elif ch == ord("a"):
            f.set_afc(not f.afc())
        elif ch == ord("s"):
            f.set_squelch(not f.squelch())
        elif ch == ord("r"):
            f.set_rsid(not f.rsid())
        elif ch == ord("x"):
            f.set_txid(not f.txid())
        elif ch == ord(","):
            f.set_frequency(f.frequency() - 100)
        elif ch == ord("."):
            f.set_frequency(f.frequency() + 100)
        elif ch == ord("<"):
            f.set_frequency(f.frequency() - 1000)
        elif ch == ord(">"):
            f.set_frequency(f.frequency() + 1000)
        elif ch == 17:
            return False
        return True


def main(stdscr, settings):
    curses.curs_set(1)
    curses.use_default_colors()
    try:
        curses.start_color()
    except curses.error:
        pass
    colours.apply(settings["COLOUR"])
    stdscr.keypad(True)
    stdscr.timeout(settings["POLL_MS"])

    deck = Deck(stdscr, settings)
    while True:
        deck.poll()
        deck.draw()
        if not deck.handle(stdscr.getch()):
            break


def run():
    try:
        settings = configmod.load()
    except configmod.ConfigError as exc:
        print(f"cyberdeck.conf: {exc}", file=sys.stderr)
        return 1
    curses.wrapper(main, settings)
    return 0


if __name__ == "__main__":
    sys.exit(run())
