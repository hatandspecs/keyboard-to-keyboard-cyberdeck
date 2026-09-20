"""Run the terminal in a pty at a given grid and read the screen back.

The deck's whole point is what it looks like, so the test drives the real
application through a real pseudo-terminal and reconstructs the screen with a
terminal emulator, rather than asserting on functions in isolation.
"""
import pty, time, fcntl, termios, struct, select
import os
import sys

# src/ holds the application; tests/ holds this. Both are addressed from the
# project root so a test can be run from anywhere.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT, "src")
sys.path.insert(0, _SRC)
import pyte


def run(keys=(), cols=66, rows=20, settle=1.2):
    screen = pyte.Screen(cols, rows)
    stream = pyte.ByteStream(screen)

    pid, fd = os.forkpty()
    if pid == 0:
        os.environ["TERM"] = "xterm"
        # No remembered state: every run starts from the configured defaults,
        # or a mode chosen by one test would leak into the next.
        os.environ["CYBERDECK_STATE_PATH"] = ""
        os.environ["LINES"], os.environ["COLUMNS"] = str(rows), str(cols)
        os.chdir(_PROJECT)          # cyberdeck.conf is read from here
        os.execvp(sys.executable,
                  [sys.executable, os.path.join(_SRC, "cyberdeck.py")])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    return False
                if not data:
                    return False
                stream.feed(data)
        return True

    pump(settle)
    for k in keys:
        os.write(fd, k if isinstance(k, bytes) else k.encode())
        pump(0.35)
    os.write(fd, b"\x11")          # Ctrl-Q
    pump(0.6)
    try:
        os.close(fd); os.waitpid(pid, os.WNOHANG)
    except OSError:
        pass
    return screen


def show(title, screen):
    print(f"\n=== {title} ({screen.columns}x{screen.lines}) ===")
    print("+" + "-" * screen.columns + "+")
    for line in screen.display:
        print("|" + line + "|")
    print("+" + "-" * screen.columns + "+")
    return "\n".join(screen.display)


if __name__ == "__main__":
    body = show("startup, 66x20", run())
    ok = []
    ok.append(("callsign in the status line", "KD3CCO" in body))
    ok.append(("hint line present", "F1 menu" in body))
    ok.append(("buffer indicator present", "[RX" in body))
    # The startup note scrolls off within a second when fldigi is decoding a
    # noise floor with squelch open, so assert on what stays put: a modem
    # name in the status line only appears if fldigi answered.
    ok.append(("fldigi connected (modem in status)", "BPSK31" in body))
    ok.append(("hint line is not truncated mid-word", "abor|" not in body and "F2 tune" in body))

    over = "NOCALL de KD3CCO  testing"
    typed = show("after typing an over", run(keys=[over]))
    ok.append(("typed text appears in compose", "testing" in typed))
    # Counted from the string rather than written in: the expected number
    # changed silently when the example callsign did.
    ok.append((f"indicator counts it ({len(over)})", f"[RX {len(over)}]" in typed))

    tune = show("F2 tuning screen", run(keys=["\x1bOQ"]))   # F2 in xterm
    ok.append(("tuning screen reached", "quality" in tune or "TUNING" in tune))

    narrow = show("50x15 grid", run(cols=50, rows=15))
    ok.append(("fits a 50-column deck", "KD3CCO" in narrow))

    print()
    for name, good in ok:
        print(f"  {'PASS' if good else 'FAIL'}  {name}")
    print("\n" + ("ALL PASS" if all(g for _, g in ok) else "SOME FAILED"))
