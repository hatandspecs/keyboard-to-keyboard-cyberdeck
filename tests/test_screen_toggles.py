"""F2 and F3 as screen toggles, from wherever the operator happens to be.

The three views — conversation, tuning, mode — are a flat set, not a tree.
Identifying an unknown signal means going tune, mode, tune, mode, and a
navigation that requires Esc between each is the wrong shape for it. So both
keys reach every screen, and each is its own way back out.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from harness import check, report
from test_screen import run

F2 = "\x1bOQ"
F3 = "\x1bOR"


def body(scr):
    return "\n".join(scr.display)


def is_tune(b):
    return "TUNING" in b or "quality" in b


def is_mode(b):
    return "MODE" in b and "AUTO (RSID)" in b


def is_chat(b):
    return "F1 menu" in b and not is_tune(b) and not is_mode(b)


if __name__ == "__main__":
    print("Screen toggles")

    check("F2 from the conversation reaches tuning", is_tune(body(run(keys=[F2]))))
    check("F2 again returns to the conversation", is_chat(body(run(keys=[F2, F2]))))

    check("F3 from the conversation reaches the mode picker",
          is_mode(body(run(keys=[F3]))))
    check("F3 again returns to the conversation",
          is_chat(body(run(keys=[F3, F3]))))

    # The two asked for: straight across, without passing through the middle.
    check("F3 from the tuning screen reaches the mode picker",
          is_mode(body(run(keys=[F2, F3]))))
    check("F2 from the mode picker reaches the tuning screen",
          is_tune(body(run(keys=[F3, F2]))))

    # And back and forth repeatedly, which is the actual use.
    check("tune, mode, tune, mode holds up",
          is_mode(body(run(keys=[F2, F3, F2, F3]))))
    check("and ends on the conversation when F3 closes it",
          is_chat(body(run(keys=[F2, F3, F2, F3, F3]))))

    # The full mode list is still the mode picker as far as F3 is concerned.
    check("F3 closes the full mode list too",
          is_chat(body(run(keys=[F3, "m", F3]))))

    sys.exit(report())
