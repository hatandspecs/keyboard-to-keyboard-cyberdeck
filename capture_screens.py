"""Produce the screens for the documentation.

The chat screen is composed from the same render.* functions the application
calls, in the same order, with a scripted conversation — a real QSO cannot be
staged on the bench, and fldigi with an open squelch fills the transcript with
decoded noise. Everything else here is a live capture of the running
application through a pseudo-terminal.

Regenerate with:  python3 capture_screens.py > screens.md
"""
import calendar, sys, time
import render, menus
from session import Session

W, H = 66, 20


def compose_chat(session, fields, width=W, height=H, timestamps=True):
    """The chat screen, assembled exactly as Deck._draw_chat assembles it."""
    compose_h = 2
    body_h = height - 1 - 1 - 1 - 1 - compose_h - 1
    out = [render.status_line(fields, width),
           render.banner(fields.get("mode", ""), 1500,
                         fields.get("state") == "INH", width),
           render.rule(width)]
    out += render.transcript_lines(session.entries, width, body_h, timestamps)
    out.append(render.rule(width))
    clines, _ = render.compose_lines(
        session.compose, session.buffer_indicator(), width, compose_h)
    out += clines
    out.append(render.hint_line(width))
    return out


def frame(lines, width=W):
    top = "┌" + "─" * width + "┐"
    body = ["│" + render.plain(l).ljust(width)[:width] + "│" for l in lines]
    return "\n".join([top] + body + ["└" + "─" * width + "┘"])


def scripted_session():
    s = Session(callsign="KD3CCO", scrollback=2000)
    # timegm, not mktime: the transcript displays UTC, so the scripted
    # times have to be built in UTC or they shift by the local offset.
    base = calendar.timegm((2026, 9, 19, 21, 9, 0, 0, 0, 0))
    def at(mins, who, text):
        s.entries.append(type(s.entries[0] if s.entries else None, (), {})) if False else None
        from session import Entry
        e = Entry(who, text, when=base + mins * 60)
        e.closed = True
        s.entries.append(e)
    at(0, "RX", "KD3CCO de W3TM  good copy, 599 here in State College. "
                "rig is an FTX-1 running 20 watts into a vertical.")
    at(2, "KD3CCO", "W3TM de KD3CCO  copy 100 percent. this is a pi 3a+ "
                    "running fldigi headless behind a terminal i wrote.")
    at(4, "RX", "that is excellent. what modes does it do?")
    at(5, "--", "mode changed to BPSK63")
    for c in "W3TM de KD3CCO  all the fldigi keyboard modes — psk, olivia, mfsk, rtty":
        s.type(c)
    return s


FIELDS = dict(call="KD3CCO", freq="14.070.589", sideband="PKTUSB", mode="BPSK63",
              carrier="1500Hz", snr="S/N 18", imd="IMD -24",
              state="RX", clock="2114Z")


def tuning_screen(width=W, height=H):
    """The F2 screen, composed as Deck._draw_tune composes it."""
    q, bar_w = 62, max(10, width - 22)
    filled = int(bar_w * q / 100)
    rows = [
        f"  rig      {render.frequency(14070589)}  PKTUSB",
        f"  carrier  1500 Hz        width  "
        f"{render.mode_bandwidth('BPSK63', 0)}",
        "  S/N      18 dB",
        "  IMD      -24 dB",
        "",
        f"  quality  {'█' * filled}{'░' * (bar_w - filled)}  {q}",
        "",
        "  AFC on    squelch on  (5)   RSID on    TXID on",
    ]
    lines = [render.status_line({**FIELDS, "call": "TUNING"}, width),
             render.banner(FIELDS.get("mode", ""), 1500, False, width)]
    for r in rows:
        lines.append([(r[:width - 1], "bright")])
    while len(lines) < height - 4:
        lines.append([("", "bright")])
    lines = lines[:height - 4]
    lines.append(render.rule(width))
    lines.append([("  ← →  carrier ±10 Hz      ↑ ↓  search signal", "dim")])
    lines.append([("  , .  VFO ±100 Hz         < >  VFO ±1 kHz", "dim")])
    lines.append([("  a AFC  s squelch  r RSID  x TXID   F2/Esc back", "dim")])
    return lines


if __name__ == "__main__":
    s = scripted_session()
    print("## The conversation screen\n")
    print("```")
    print(frame(compose_chat(s, FIELDS)))
    print("```\n")

    print("## The tuning screen — F2\n")
    print("```")
    print(frame(tuning_screen()))
    print("```\n")

    print("## The menu — F1\n")
    print("```")
    print(frame(menus.render(menus.ROOT, W, H, selected=2)))
    print("```\n")

    print("## The mode picker — F3\n")
    print("```")
    print(frame(menus.render(menus.mode_menu("BPSK63"), W, H)))
    print("```\n")

    names = menus.keyboard_modes([n for _, n in menus.MODE_TIER1] + [
        "BPSK125", "BPSK250", "BPSK500", "QPSK63", "QPSK125", "QPSK250",
        "OLIVIA-4/250", "OLIVIA-16/500", "OLIVIA-32/1K", "MFSK8", "MFSK32",
        "MFSK64", "THOR16", "THOR25", "THOR50x1", "DOMEX4", "DOMEX5",
        "DOMEX11", "DOMEX16", "DOMEX22", "CONTESTIA", "RTTY"])
    menu, *_ = menus.paged_menu("ALL MODES", names, 0, W, H)
    print("## The full modem list — F3 then m\n")
    print("```")
    print(frame(menus.render(menu, W, H)))
    print("```")
