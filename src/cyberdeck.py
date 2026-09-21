#!/usr/bin/env python3
"""Keyboard-to-keyboard terminal for fldigi.

The only thing on the screen: a status line, the conversation, and what is
being typed. No window manager, no pointer, nothing to click. fldigi does the
modem work invisibly behind an XML-RPC connection (docs/design_doc.md §4).

Run it over SSH for development; on the deck it runs on tty1 against the
framebuffer, where the color schemes use the real palette.
"""

import curses
import json
import os
import sys
import time

import colors
import config as configmod
import menus
import render
from fldigi_client import Fldigi
from session import Entry, Session, RX, TX

CHAT, TUNE = "chat", "tune"

# Releasing the post-over receive hold. Not configuration: these describe how
# a decaying transient is told apart from a station answering, which is a
# property of the problem rather than a preference. See
# Deck._settling_after_over.
SETTLE_POLLS = 2        # consecutive good polls before decodes are trusted
SETTLE_QUALITY = 20.0   # 0-100, used only when fldigi's squelch is off



class _Memories(dict):
    """format_map helper: an unknown {token} is left alone rather than
    raising, so a memory with a typo in it still inserts."""

    def __missing__(self, key):
        return "{" + key + "}"


class Deck:
    def __init__(self, stdscr, settings):
        self.scr = stdscr
        self.cfg = settings
        self.scheme = settings["COLOR"]
        self.screen = CHAT
        self.scroll = 0
        # Which menu is open, if any, and where in a paged list. A single
        # value rather than a stack: the tree is two deep by design, and
        # Esc from anywhere returns to the conversation.
        self.menu = None
        self.menu_page = 0
        self.menu_sel = 0
        # When a field is being edited in place:
        #   {"key": "MEMORY_7" | "CALLSIGN", "title": str, "text": str,
        #    "cursor": int}
        self.edit = None
        self._page_keys = {}
        self.status_note = ""
        self._tx_seen = False
        self._tx_echo = ""
        # When the last over finished, for the post-transmit receive hold.
        self._tx_ended = 0.0
        # Whether that hold is currently running, and how many consecutive
        # polls have reported a signal worth releasing it for.
        self._settling = False
        self._settle_good = 0
        # The last of what has been decoded, for the tuning screen's preview.
        # Held separately from the transcript because it has to survive the
        # transcript being cleared and has to be cheap to take the tail of.
        self._rx_tail = ""
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

        # After the configured defaults, so that what was last chosen wins.
        self._load_state()
        if self.fldigi.connected and settings.get("REMEMBER_STATE") == "yes":
            self.session.note(f"resumed {self.fldigi.modem()} at "
                              f"{self.fldigi.carrier()} Hz, "
                              f"{colors.SCHEMES[self.scheme]['name']}")

        # Powering on into a transmit-capable state is the wrong default for a
        # deck that lives in a bag: a stray Ctrl-T on a radio connected to an
        # unknown antenna is worse than an extra keystroke before the first
        # over. Cleared with Ctrl-I, or F1 6 i.
        if self.fldigi.connected:
            self._set_rig_mode()
            if settings["RSID_ON_START"] == "yes" and not self.fldigi.rsid():
                self.fldigi.set_rsid(True)
                self.session.note("RSID on — will follow other stations' modes")

        if settings["INHIBIT_ON_START"] == "yes":
            self.session.inhibit(True)
            self.fldigi.receive_only(True)
            self.session.note("transmit INHIBITED at startup — Ctrl-I to enable")

    # -- fldigi ------------------------------------------------------------

    def poll(self):
        # fldigi echoes transmitted text back through its RX buffer, so text
        # read while the radio is keyed is our own coming back — recording it
        # would enter every over twice, once from the keyboard and once as
        # though a correspondent had sent it.
        #
        # The buffer is still drained rather than skipped: poll_rx() advances
        # its read position, and leaving the echo in place would deliver the
        # whole over in one lump the moment we returned to receive.
        #
        # fldigi's own TX state decides this, not the session's. Ctrl-Y ends
        # the over immediately but fldigi keeps sending until its buffer
        # drains, and the echo keeps arriving for that whole tail.
        text = self.fldigi.poll_rx()
        sending = self.fldigi.trx_state() != "RX"

        # The end of the over is established before anything is done with
        # `text`, because the poll in which trx_state flips to RX still
        # carries the tail of our own echo: fldigi's echo and its TX state do
        # not change over atomically. Deciding delivery first delivered that
        # tail to the transcript as though a correspondent had sent it.
        if sending:
            self._tx_seen = True
        elif self._tx_seen:
            # fldigi has finished draining and dropped back to receive. This
            # is the moment the over is really over: Ctrl-Y only stops adding
            # to the buffer.
            self._tx_seen = False
            self._tx_echo = ""
            self._tx_ended = time.monotonic()
            self._settling = True
            self._settle_good = 0
            self.session.note("sent")

        holding = self._settling_after_over(sending)

        if text and not sending and not holding:
            self.session.receive(text)
            self._rx_tail = (self._rx_tail + text)[-400:]
            self.scroll = 0
        elif text and sending:
            # Our own transmission, echoed back by fldigi as it goes out.
            # Held here rather than written to the transcript: it is drawn as
            # a transient TX line under the over while sending, and dropped
            # when the over completes. See docs/design_doc.md §5.5 for why this is
            # transient rather than permanent.
            self._tx_echo += text
            self.scroll = 0
        # Text arriving while holding falls through to neither branch and is
        # dropped. Discarding it is the point; accumulating it into the echo
        # would carry the transient over into the next over's TX line.

        if self.session.tx_timed_out():
            self.fldigi.abort()
            self.session.abort()
            self.session.note(f"transmit timed out after {self.cfg['TX_TIMEOUT']}s")

    def _settling_after_over(self, sending):
        """True while decodes arriving after an over should be discarded.

        RTTY is the mode that needs this. Baudot has no error detection at
        all — five bits between a start and a stop bit — so any noise that
        fits the frame decodes as a character. When PTT drops the receiver
        unmutes and the AGC recovers, and the modem turns that transient into
        text. It is real audio and fldigi is right to decode it; it is simply
        not anybody's transmission. The tail of our own echo lands in the same
        window.

        A fixed timer is the obvious instrument and the wrong one on its own.
        Long enough to cover the transient on a quiet band is long enough to
        swallow the opening characters of a fast reply in a contest, and a
        timer cannot tell those apart. So the timer is only the floor:

        * below ``RX_HOLD_MS``, always discard — at PTT drop even the quality
          metric is still settling, so there is nothing trustworthy to gate on;
        * after that, discard until the modem reports a real signal on two
          consecutive polls. A decaying transient does not sustain; a
          correspondent answering does;
        * give up at ``RX_HOLD_MAX_MS``, so a band with nothing on it returns
          to normal behavior instead of blanking indefinitely.

        ``RX_HOLD_MAX_MS = 0`` disables the quality gate and leaves exactly the
        fixed ``RX_HOLD_MS`` window, which is what this did before.

        Nothing is cleared. ``poll_rx()`` drains and this discards, so the
        chunk delivered on release holds only what arrived since the last
        poll. Calling ``clear_rx()`` on release would throw away the opening
        of the very reply that ended the hold.
        """
        if not self._settling or sending:
            return False

        elapsed = time.monotonic() - self._tx_ended
        floor = self.cfg.get("RX_HOLD_MS", 0) / 1000.0
        ceiling = self.cfg.get("RX_HOLD_MAX_MS", 0) / 1000.0

        if elapsed < floor:
            return True
        if ceiling <= 0 or elapsed >= ceiling:
            self._settling = False
            return False

        # fldigi's squelch level is the operator's own statement of what
        # counts as a signal here, so it is the right threshold when squelch
        # is on. With squelch off no such statement exists and a constant
        # stands in. Either way the transient has to hold above it rather than
        # merely touch it, which is what the consecutive-poll count is for.
        threshold = (self.fldigi.squelch_level() if self.fldigi.squelch()
                     else SETTLE_QUALITY)
        if self.fldigi.quality() >= threshold:
            self._settle_good += 1
        else:
            self._settle_good = 0
        if self._settle_good >= SETTLE_POLLS:
            self._settling = False
            return False
        return True

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
            "freq": render.frequency(freq),
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

        if self.edit is not None:
            self._draw_edit(h, w)
        elif self.menu:
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

        entries = self.session.entries
        if self._tx_seen and self._tx_echo:
            # A transient line showing what fldigi has actually put on the air
            # so far, under the over as typed. Not part of the session: it is
            # gone the moment the over completes.
            entries = list(entries) + [Entry("TX", self._tx_echo)]
        lines = render.transcript_lines(
            entries, w, body_h,
            timestamps=self.cfg["TIMESTAMPS"] == "yes", scroll=self.scroll)
        for i, line in enumerate(lines):
            self._put(2 + i, 0, line, w)

        rule_row = 2 + body_h
        self._put(rule_row, 0, render.rule(w), w)

        clines, (crow, ccol) = render.compose_lines(
            self.session.compose, self.session.buffer_indicator(), w, compose_h,
            cursor=self.session.cursor)
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

        rows = render.tune_rows({
            "freq": render.frequency(f.frequency()),
            "rig_mode": f.rig_mode(),
            "carrier": f.carrier(),
            "width": render.mode_bandwidth(f.modem(), f.bandwidth()),
            "snr": f.signal_to_noise(),
            "imd": f.imd(),
            "quality": f.quality(),
            "afc": f.afc(),
            "squelch": f.squelch(),
            "squelch_level": f.squelch_level(),
            "rsid": f.rsid(),
            "txid": f.txid(),
            "reverse": f.reverse(),
            "preview": self._rx_tail,
            "note": self.session.last_note,
        }, w)
        for i, text in enumerate(rows):
            if 2 + i < h - 4:
                self._put(2 + i, 0, [(text[:w - 1], "bright")], w)

        self._put(h - 4, 0, render.rule(w), w)
        for i, hint in enumerate(render.TUNE_HINTS):
            self._put(h - 3 + i, 0, [(hint[:w - 1], "dim")], w)

    def _menu_for(self, which, w, h):
        """The menu structure for a name, for navigation and hit-testing."""
        saved, self.menu = self.menu, which
        try:
            return self._current_menu(w, h)
        finally:
            self.menu = saved

    def _current_menu(self, w, h):
        f, m = self.fldigi, self.menu
        if m == "root":
            return menus.ROOT
        if m == "display":
            return menus.DISPLAY
        if m == "tuning":
            return menus.tuning_menu(f.afc(), f.squelch(), f.squelch_level(),
                                     f.rsid(), f.txid(), f.reverse(),
                                     self.cfg.get("RX_HOLD_MS", 0),
                                     self.cfg.get("RX_HOLD_MAX_MS", 0))
        if m == "radio":
            return menus.band_menu(self._supported_bands())
        if m == "system":
            return menus.SYSTEM
        if m == "station":
            return menus.station_menu(self.cfg)
        if m == "memories":
            return menus.memories_menu(self.cfg)
        if m == "mode":
            return menus.mode_menu(f.modem(), auto=f.rsid())
        if m == "modes_all":
            menu, self.menu_page, _, self._page_keys = menus.paged_menu(
                "ALL MODES", menus.keyboard_modes(f.modem_names()),
                self.menu_page, w, h)
            return menu
        return menus.ROOT

    def _draw_menu(self, h, w):
        menu = self._current_menu(w, h)
        for i, line in enumerate(menus.render(menu, w, h, self.menu_sel)):
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
                self.scr.addstr(row, x, chunk, colors.attr(kind))
            except curses.error:
                pass
            x += len(chunk)

    # -- keyboard ----------------------------------------------------------

    def handle(self, ch):
        """Returns False to quit."""
        if ch == -1:
            return True

        if self.edit is not None:
            return self._handle_edit(ch)

        if self.menu:
            return self._handle_menu(ch)

        if self.screen == TUNE:
            return self._handle_tune(ch)

        if ch == curses.KEY_F1:
            self._open_menu("root")
        elif ch == curses.KEY_F3:
            self._open_menu("mode")
        elif ch == curses.KEY_F2:
            # The preview starts empty on every visit. Carrying the last
            # visit's decodes in means the first thing the screen shows is
            # text from a different frequency, which is worse than showing
            # nothing: the preview exists to confirm that what is being tuned
            # *now* is producing copy.
            self._rx_tail = ""
            self.screen = TUNE
        elif ch == curses.KEY_F4:
            self._apply_scheme(colors.cycle(self.scheme))
        elif ch == 20:                       # Ctrl-T
            text = self.session.start_over()
            if text is not None:
                self._tx_echo = ""
                self.fldigi.start_over(text)
        elif ch == 25:                       # Ctrl-Y
            if self.session.hand_back():
                self.fldigi.hand_back()
        elif ch == 3:                        # Ctrl-C
            # Record how much actually went out before the abort. This is the
            # one case where intent and reality differ and the difference
            # matters, so it is kept rather than dropped with the transient
            # progress line.
            partial = self._tx_echo.strip()
            self.fldigi.abort()
            self.session.abort()
            if partial:
                self.session.note(f"aborted — sent: {partial}")
            self._tx_echo = ""
        elif ch == 12:                       # Ctrl-L
            self.scr.clearok(True)
        elif ch == 9:                        # Ctrl-I, and Tab: same byte
            self._toggle_inhibit()
        elif ch == 24:                       # Ctrl-X
            self._clear_transcript()
        # On the conversation screen the arrows edit the line, as they would
        # in any terminal: left and right move the cursor, up and down recall
        # what was sent before.
        elif ch == curses.KEY_LEFT:
            self.session.move(-1)
        elif ch == curses.KEY_RIGHT:
            self.session.move(1)
        elif ch == curses.KEY_UP:
            self.session.recall(-1)
        elif ch == curses.KEY_DOWN:
            self.session.recall(1)
        elif ch == curses.KEY_HOME:
            self.session.home()
        elif ch == curses.KEY_END:
            self.session.end()

        # Tuning without leaving the transcript, on the WASD cluster under the
        # left hand. NOT on Ctrl+arrows: the Linux console cannot send a
        # modified arrow at all — TERM=linux defines no kUP5 or kLFT5, so
        # ncurses sees a plain KEY_UP whether or not Ctrl is held. That would
        # have worked over SSH from an xterm and silently not on the panel.
        elif ch == 1:                        # Ctrl-A
            self.fldigi.nudge_carrier(-10)
        elif ch == 4:                        # Ctrl-D
            self.fldigi.nudge_carrier(10)
        elif ch == 23:                       # Ctrl-W
            self._search(self.fldigi.search_up, "up")
        elif ch == 19:                       # Ctrl-S
            self._search(self.fldigi.search_down, "down")
        # Ctrl-Z arrives as one of two different values depending on the
        # terminal, and the panel gets the one that is easy to miss.
        # TERM=linux defines kspd=^Z, so ncurses consumes byte 26 and returns
        # KEY_SUSPEND (407) instead; TERM=xterm defines no kspd and the byte
        # comes through as 26. Matching only 26 works over SSH and silently
        # does nothing on the deck — which is how this shipped. kspd is the
        # only such capability in the linux entry, so Ctrl-Z is the only
        # command key affected; kbs=^? is already handled with backspace.
        elif ch in (26, curses.KEY_SUSPEND):  # Ctrl-Z
            if not self.session.undo():
                self.session.note("nothing to undo")
        elif curses.KEY_F5 <= ch <= curses.KEY_F12:
            self._insert_memory(ch - curses.KEY_F0)
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
        else:
            # Same reasoning as the tuning screen: a key that appears dead is
            # otherwise indistinguishable from one whose handler ran and did
            # nothing visible. Caps Lock cost an hour that way.
            name = curses.keyname(ch).decode(errors="replace") if ch >= 0 else "?"
            print(f"chat: unhandled key {ch} ({name})", file=sys.stderr)
        return True

    # -- remembered state --------------------------------------------------
    #
    # What the operator last chose, restored on the next start so the deck
    # comes back as it was left. Deliberately NOT including the transmit
    # inhibit: that is re-asserted on every power-on regardless, because a
    # deck coming out of a bag able to key a radio attached to an unknown
    # antenna is the thing INHIBIT_ON_START exists to prevent. Convenience
    # does not get to override that.

    def _state_path(self):
        # The environment wins, so a test run can point this somewhere
        # disposable — otherwise each run would inherit the previous one's
        # mode and the configured DEFAULT_MODE would never be exercised.
        # Empty means "do not remember", which is what the tests use.
        override = os.environ.get("CYBERDECK_STATE_PATH")
        if override is not None:
            return os.path.expanduser(override) or None
        if self.cfg.get("REMEMBER_STATE") != "yes":
            return None
        return os.path.expanduser(self.cfg.get("STATE_PATH") or "")

    def _load_state(self):
        """Apply the remembered mode, carrier, color and timestamps."""
        path = self._state_path()
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            return          # absent or corrupt: the configured defaults stand
        if state.get("timestamps") in ("yes", "no"):
            self.cfg["TIMESTAMPS"] = state["timestamps"]
        for slot, text in (state.get("memories") or {}).items():
            if slot.isdigit() and 5 <= int(slot) <= 12:
                # A memory set on the deck wins over cyberdeck.conf's default,
                # which is only a starting point.
                self.cfg[f"MEMORY_{int(slot)}"] = text
        known = {k for k, _l, _t in menus.STATION_FIELDS}
        for field, value in (state.get("station") or {}).items():
            if field in known:
                self.cfg[field] = value
        self.session.callsign = self.cfg.get("CALLSIGN") or "LOCAL"
        for key, field in (("rx_hold_ms", "RX_HOLD_MS"),
                           ("rx_hold_max_ms", "RX_HOLD_MAX_MS")):
            hold = state.get(key)
            if isinstance(hold, int) and 0 <= hold <= 5000:
                self.cfg[field] = hold
        scheme = state.get("color")
        if scheme in colors.SCHEMES:
            self.scheme = scheme
            colors.apply(scheme)
        if self.fldigi.connected:
            if state.get("mode"):
                self.fldigi.set_modem(state["mode"])
            if state.get("carrier"):
                self.fldigi.set_carrier(state["carrier"])

    def _save_state(self):
        """Never raises: failing to remember a preference must not disturb a
        contact in progress."""
        path = self._state_path()
        if not path:
            return
        state = {
            "color": self.scheme,
            "timestamps": self.cfg["TIMESTAMPS"],
            "mode": self.fldigi.modem() if self.fldigi.connected else None,
            "carrier": self.fldigi.carrier() if self.fldigi.connected else None,
            "memories": {str(n): self.cfg.get(f"MEMORY_{n}", "")
                         for n in range(5, 13)},
            "station": {k: self.cfg.get(k, "")
                        for k, _label, _token in menus.STATION_FIELDS},
            "rx_hold_ms": self.cfg.get("RX_HOLD_MS", 0),
            "rx_hold_max_ms": self.cfg.get("RX_HOLD_MAX_MS", 0),
        }
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".new"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            os.replace(tmp, path)       # atomic: no truncated file after a cut
        except OSError:
            pass

    def _apply_scheme(self, name):
        """Switch color scheme and force the whole screen to be repainted.

        The repaint is not cosmetic. fbcon resolves a glyph's color when it is
        drawn, so redefining a palette entry does NOT recolor anything already
        on screen — and ncurses repaints only cells whose content or pair
        NUMBER changed. Changing scheme changes neither: the text is the same
        and the pair is still pair 3, only its definition moved. So without
        this, a scheme change leaves the old colors up until something else
        happens to rewrite those cells, which is why the status bar kept the
        previous scheme's color and one stale cell sat green in the corner.
        """
        self.scheme = name
        colors.apply(name)
        self.scr.clearok(True)
        self.scr.touchwin()
        # No transcript note: the scheme change is self-evident on screen and
        # a log of it is noise in the middle of a contact.
        self._save_state()

    def _open_menu(self, which):
        self.menu = which
        self.menu_page = 0
        self.menu_sel = self._first_selectable(which)

    def _close_menu(self):
        self.menu = None
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _first_selectable(self, which):
        h, w = self.scr.getmaxyx()
        menu = self._menu_for(which, w, h)
        opts = menus.selectable(menu)
        return opts[0] if opts else 0

    def _handle_menu(self, ch):
        f, m = self.fldigi, self.menu
        # Case-folded for the same reason as the tuning screen: every
        # single-key shortcut here is a letter or a digit, and none of them
        # should stop working because Caps Lock is on.
        key = chr(ch).lower() if 32 <= ch < 127 else ""

        # Arrow-key navigation. The single-key shortcuts still work — this is
        # an addition, not a replacement — but a menu you can walk with the
        # arrows and confirm with Enter needs no memorised letters, which is
        # what a deck used occasionally rather than daily wants.
        h, w = self.scr.getmaxyx()
        menu = self._menu_for(m, w, h)
        opts = menus.selectable(menu)
        if opts and ch in (curses.KEY_UP, curses.KEY_DOWN):
            if self.menu_sel in opts:
                at = opts.index(self.menu_sel)
            else:
                at = 0
            at = (at + (1 if ch == curses.KEY_DOWN else -1)) % len(opts)
            self.menu_sel = opts[at]
            return True
        if ch in (10, 13, curses.KEY_ENTER) and opts:
            # Enter acts as though the selected row's own key was pressed, so
            # both paths go through one dispatch and cannot drift apart.
            sel = self.menu_sel if self.menu_sel in opts else opts[0]
            key = menu["items"][sel][0]
            ch = ord(key) if len(key) == 1 else ch

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
                    "4": "display", "5": "memories", "6": "station",
                    "7": "system"}.get(key)
            if dest:
                self._open_menu(dest)
            return True

        if m == "mode":
            if key == "a":
                on = not f.rsid()
                f.set_rsid(on)
                self.session.note(
                    "AUTO on — will follow other stations' mode identifiers"
                    if on else "AUTO off — mode stays where you put it")
                self._close_menu(); return True
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
                self._apply_scheme(scheme)
                self._close_menu()
            elif key == "t":
                self.cfg["TIMESTAMPS"] = "no" if self.cfg["TIMESTAMPS"] == "yes" else "yes"
                self.session.note(f"timestamps {self.cfg['TIMESTAMPS']}")
                self._save_state()
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
            elif key == "v":
                on = not f.reverse()
                f.set_reverse(on)
                self.session.note(f"mark/space reversed {'on' if on else 'off'}")
            elif key == "+":
                f.set_squelch_level(min(100.0, f.squelch_level() + 5))
            elif key == "-":
                f.set_squelch_level(max(0.0, f.squelch_level() - 5))
            elif key in ("[", "]", "{", "}"):
                # The lower bound is always discarded; the upper bound caps
                # how long the quality gate may keep waiting. Kept ordered on
                # every change rather than validated on use, so the pair
                # cannot be left describing an impossible window.
                up = key in ("]", "}")
                which = "RX_HOLD_MS" if key in ("[", "]") else "RX_HOLD_MAX_MS"
                step = 250 if up else -250
                value = max(0, min(5000, self.cfg.get(which, 0) + step))
                self.cfg[which] = value
                if which == "RX_HOLD_MS":
                    most = self.cfg.get("RX_HOLD_MAX_MS", 0)
                    if most and most < value:
                        self.cfg["RX_HOLD_MAX_MS"] = value
                elif value and value < self.cfg.get("RX_HOLD_MS", 0):
                    self.cfg["RX_HOLD_MS"] = value
                self._save_state()
                least = self.cfg.get("RX_HOLD_MS", 0)
                most = self.cfg.get("RX_HOLD_MAX_MS", 0)
                self.session.note(
                    f"RX hold {least} ms"
                    + (f" to {most} ms" if most else " (fixed window)"))
            elif key == "c":
                f.set_carrier(self.cfg["DEFAULT_CARRIER"])
                self.session.note(f"carrier parked at {self.cfg['DEFAULT_CARRIER']} Hz")
                self._save_state()
                self._close_menu()
            return True

        if m == "radio":
            hz = menus.BAND_FREQUENCIES.get(key)
            if hz:
                label = next(lbl for k, lbl, _d, _h in menus.BANDS if k == key)
                allowed = self._supported_bands()
                if allowed is not None and label not in allowed:
                    self.session.note(f"{label} is not supported by this radio")
                else:
                    self._set_vfo(hz, label=render.frequency(hz))
                    self._set_rig_mode()
                self._close_menu()
            return True

        if m == "memories":
            if key.isdigit() and 1 <= int(key) <= 8:
                slot = int(key) + 4
                self._open_editor(f"MEMORY_{slot}", f"F{slot}")
            return True

        if m == "station":
            if key.isdigit() and 1 <= int(key) <= len(menus.STATION_FIELDS):
                field_key, label, _token = menus.STATION_FIELDS[int(key) - 1]
                self._open_editor(field_key, label)
            return True

        if m == "system":
            if key == "i":
                self._toggle_inhibit()
                self._close_menu()
            elif key == "c":
                self._clear_transcript()
                self._close_menu()
            elif key == "q":
                return False
            return True

        return True

    def _set_vfo(self, hz, label=None):
        """Command the radio's VFO and check it actually went there.

        fldigi keeps its own frequency and refreshes it from the rig, so a
        command the radio ignores shows up as the deck's number snapping back
        a moment later — which reads as the deck fighting the radio when it is
        really the radio declining.

        This asks once and reports the result. It deliberately does NOT
        re-assert: a loop that re-sends whenever the readback disagrees cannot
        tell a rejected command from the operator turning the knob, so it
        would fight a deliberate manual tune and never let go. One command,
        one answer, and the truth on screen.
        """
        hz = int(hz)
        self.fldigi.set_frequency(hz)
        time.sleep(0.35)          # let the command reach the rig and read back
        got = int(self.fldigi.frequency() or 0)
        where = label or render.frequency(hz)
        if abs(got - hz) <= 5:
            self.session.note(f"VFO {render.frequency(got)}"
                              + (f"  {self.fldigi.rig_mode()}" if label else ""))
            return True
        self.session.note(f"VFO {where} refused — radio stayed on "
                          f"{render.frequency(got)}")
        return False

    # -- editing a message memory in place --------------------------------

    def _toggle_inhibit(self):
        self.session.inhibit(not self.session.inhibited)
        self.fldigi.receive_only(self.session.inhibited)

    def _clear_transcript(self):
        """Empty the transcript and fldigi's receive buffer together.

        The decode preview keeps its own tail, so the tuning screen does not
        go blank just because the conversation was cleared — they answer
        different questions.
        """
        self.session.entries.clear()
        self.fldigi.clear_rx()
        self.scroll = 0
        self.session.note("transcript cleared")

    def _open_editor(self, key, title):
        text = self.cfg.get(key, "") or ""
        self.edit = {"key": key, "title": title, "text": text,
                     "cursor": len(text)}

    def _draw_edit(self, h, w):
        e = self.edit
        self._put(0, 0, [(f" EDIT  {e['title']}".ljust(w), "reverse")], w)
        self._put(1, 0, render.rule(w), w)

        body_h = max(1, h - 5)
        lines, (crow, ccol) = render.compose_lines(
            e["text"], "", w, body_h, cursor=e["cursor"])
        for i, line in enumerate(lines):
            self._put(2 + i, 0, line, w)

        self._put(h - 3, 0, render.rule(w), w)
        self._put(h - 2, 0, [(render.EDIT_HINT[:w - 1], "dim")], w)
        if e["key"].startswith("MEMORY_"):
            self._put(h - 1, 0, [(render.EDIT_TOKENS_HINT[:w - 1], "dim")], w)
        try:
            curses.curs_set(1)
            self.scr.move(2 + crow, ccol)
        except curses.error:
            pass

    def _handle_edit(self, ch):
        e = self.edit
        if ch == 27:                                   # Esc: discard
            self.edit = None
        elif ch in (10, 13, curses.KEY_ENTER):         # Enter: store
            text = e["text"].strip()
            self.cfg[e["key"]] = text
            if e["key"] == "CALLSIGN":
                # The transcript attributes our own overs by callsign, so the
                # session has to be told rather than reading it once at start.
                self.session.callsign = text or "LOCAL"
            self._save_state()
            self.session.note(f"{e['title']} "
                              + ("cleared" if not text else "saved"))
            self.edit = None
        elif ch == 21:                                 # Ctrl-U: clear the line
            e["text"], e["cursor"] = "", 0
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if e["cursor"] > 0:
                e["text"] = e["text"][:e["cursor"] - 1] + e["text"][e["cursor"]:]
                e["cursor"] -= 1
        elif ch == curses.KEY_DC:                      # Delete: forwards
            e["text"] = e["text"][:e["cursor"]] + e["text"][e["cursor"] + 1:]
        elif ch == curses.KEY_LEFT:
            e["cursor"] = max(0, e["cursor"] - 1)
        elif ch == curses.KEY_RIGHT:
            e["cursor"] = min(len(e["text"]), e["cursor"] + 1)
        elif ch == curses.KEY_HOME:
            e["cursor"] = 0
        elif ch == curses.KEY_END:
            e["cursor"] = len(e["text"])
        elif ch == 17:                                 # Ctrl-Q
            return False
        elif 32 <= ch < 127:
            e["text"] = e["text"][:e["cursor"]] + chr(ch) + e["text"][e["cursor"]:]
            e["cursor"] += 1
        return True

    def _insert_memory(self, slot):
        """Put message memory `slot` in at the cursor.

        The station's own details are substituted rather than written into
        each memory, so changing the callsign does not mean rewriting them.
        """
        raw = (self.cfg.get(f"MEMORY_{slot}") or "").strip()
        if not raw:
            self.session.note(f"F{slot} is empty — set it from F1 5")
            return
        text = raw.format_map(_Memories({
            "call": self.cfg.get("CALLSIGN", ""),
            "name": self.cfg.get("NAME", ""),
            "qth": self.cfg.get("QTH", ""),
            "grid": self.cfg.get("LOCATOR", ""),
            # {locator} kept as an alias: memories written before the token
            # was renamed still work rather than inserting a literal brace.
            "locator": self.cfg.get("LOCATOR", ""),
            "rig": self.cfg.get("RIG", ""),
        }))
        out = self.session.insert(text)
        if out:
            self.fldigi.send_more(out)
        self.scroll = 0

    def _search(self, fn, direction):
        """Run fldigi's signal search and say what happened.

        The search either lands the carrier on a signal or leaves it where it
        was, and the difference is invisible on a screen with no waterfall —
        which reads as a dead key when the band is quiet. Report the move.
        """
        f = self.fldigi
        before = f.carrier()
        fn()
        time.sleep(0.4)          # fldigi needs a moment to settle on a signal
        after = f.carrier()
        if after != before:
            self.session.note(f"search {direction}: carrier {before} -> {after} Hz")
        else:
            self.session.note(f"search {direction}: nothing found above the "
                              f"squelch; still {after} Hz")

    def _supported_bands(self):
        """Band labels this radio covers, or None for all of them.

        Configured rather than probed. hamlib can report a rig's frequency
        ranges through dump_caps, which would make this automatic — but the
        deck has no reason to trust a range list it has never tested against,
        and a wrong answer here silently hides a band the operator can
        actually use.
        """
        raw = (self.cfg.get("RIG_BANDS") or "").strip()
        if not raw:
            return None
        return {part.strip() for part in raw.split(",") if part.strip()}

    def _set_rig_mode(self):
        """Put the radio into the sideband digital work needs.

        Digital modes are upper sideband on every band, including 40 and 80
        where voice is lower — so this is not something to leave to the
        operator's memory at the moment they change bands. PKTUSB is the
        alternative when the radio's own data mode is wanted; which one is
        right depends on how the FTX-1 is configured to route USB audio.
        """
        want = (self.cfg.get("RIG_MODE") or "").strip()
        if not want:
            return
        current = self.fldigi.rig_mode()
        if current == want:
            return
        available = self.fldigi.rig_modes()
        if available and want not in available:
            self.session.note(f"rig will not take mode {want}; left as {current}")
            return
        self.fldigi.set_rig_mode(want)
        # Say so. Silently changing the radio's mode out from under the
        # operator is how a deck ends up transmitting through the speech
        # processor, or reverts a deliberate choice with no trace.
        self.session.note(f"rig mode {current or '?'} -> {want}")

    def _set_mode(self, name):
        """Change modem, keeping the carrier where it is.

        fldigi resets the carrier to its sweet spot when the modem changes.
        That is right when starting fresh and wrong for the job this screen
        mostly does: identifying an unknown signal by trying modes against it.
        The operator has already tuned onto the signal, and throwing that away
        on every attempt means re-tuning before each guess — with the added
        trap that a mode which *would* have decoded fails because it is now
        pointed at empty spectrum.

        So the carrier is read before the change and written back after.
        `c` on the Tune Settings page parks it deliberately, which is the
        other half of the behaviour and stays available.
        """
        was = self.fldigi.carrier()
        self.fldigi.set_modem(name)
        # Only if it actually moved, and only to somewhere sane: a failed read
        # returns 0, and writing that back would park the modem at DC.
        now = self.fldigi.carrier()
        if was and now != was:
            self.fldigi.set_carrier(was)
            now = self.fldigi.carrier()
        self.session.note(f"mode changed to {self.fldigi.modem()} at {now} Hz")
        self._save_state()
        self._close_menu()

    def _typed(self, char):
        out = self.session.type(char)
        if out:
            self.fldigi.send_more(out)
        self.scroll = 0

    def _handle_tune(self, ch):
        f = self.fldigi
        # Case-folded: a command key must not depend on Caps Lock or a held
        # shift. The deck reported "unhandled key 65 (A)" for every letter on
        # this screen until this was fixed, which looked exactly like the
        # bindings being dead.
        key = chr(ch).lower() if 32 <= ch < 127 else ""
        if ch in (curses.KEY_F2, 27):
            self.screen = CHAT
        elif ch == curses.KEY_LEFT:
            f.nudge_carrier(-10)
        elif ch == curses.KEY_RIGHT:
            f.nudge_carrier(10)
        elif ch == curses.KEY_UP:
            self._search(f.search_up, "up")
        elif ch == curses.KEY_DOWN:
            self._search(f.search_down, "down")
        elif key == "a":
            f.set_afc(not f.afc())
        elif key == "s":
            f.set_squelch(not f.squelch())
        elif key == "r":
            f.set_rsid(not f.rsid())
        elif key == "x":
            f.set_txid(not f.txid())
        elif key == "v":
            on = not f.reverse()
            f.set_reverse(on)
            self.session.note(f"mark/space reversed {'on' if on else 'off'}")
        elif key == "+" or key == "=":
            # '=' too: it is the unshifted key, and squelch is adjusted often
            # enough that reaching for shift each time is a nuisance.
            f.set_squelch_level(min(100.0, f.squelch_level() + 2))
        elif key == "-":
            f.set_squelch_level(max(0.0, f.squelch_level() - 2))
        elif key == ",":
            self._set_vfo(f.frequency() - 100)
        elif key == ".":
            self._set_vfo(f.frequency() + 100)
        elif key == "<":
            self._set_vfo(f.frequency() - 1000)
        elif key == ">":
            self._set_vfo(f.frequency() + 1000)
        elif ch == 17:
            return False
        else:
            # Anything this screen does not bind is reported rather than
            # silently dropped. A key that appears dead is otherwise
            # indistinguishable from a key whose handler ran and did nothing
            # visible, which cost an hour once.
            name = curses.keyname(ch).decode(errors="replace") if ch >= 0 else "?"
            print(f"tune: unhandled key {ch} ({name})", file=sys.stderr)
        return True


def main(stdscr, settings):
    curses.curs_set(1)
    curses.use_default_colors()
    try:
        curses.start_color()
    except curses.error:
        pass
    colors.apply(settings["COLOR"])
    stdscr.keypad(True)
    stdscr.timeout(settings["POLL_MS"])

    # raw(), not the cbreak() curses.wrapper leaves us in. Under cbreak the
    # terminal still interprets Ctrl-C as SIGINT, so it never reaches getch()
    # and Python unwinds with KeyboardInterrupt — on the one key whose whole
    # job is to stop a transmission. raw() delivers it as byte 3 instead.
    curses.raw()

    # Esc and the arrow keys both begin with the same byte, so ncurses waits
    # ESCDELAY for the rest of a sequence before deciding it was a bare Esc.
    # The default is a full second, which makes Esc feel broken. 100 ms is
    # comfortably longer than the few milliseconds a Bluetooth keyboard needs
    # to deliver the remaining bytes of an arrow key, and short enough that
    # Esc is instant.
    try:
        curses.set_escdelay(100)
    except (AttributeError, curses.error):
        pass

    deck = Deck(stdscr, settings)
    try:
        while True:
            deck.poll()
            deck.draw()
            if not deck.handle(stdscr.getch()):
                break
    finally:
        # Whatever happens — clean exit, crash, or a signal that still gets
        # through — do not leave the radio keyed. This runs before curses
        # tears the screen down, and is allowed to fail silently: an exception
        # here would mask the one that brought us here.
        try:
            deck.fldigi.abort()
        except Exception:
            pass
        try:
            curses.noraw()
        except curses.error:
            pass


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
