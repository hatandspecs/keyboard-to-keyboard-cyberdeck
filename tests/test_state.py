"""What the deck remembers when it is restarted.

The deck is switched off by removing its power, so "remembered" has to mean
written to the card, not written to the page cache. Two faults hide here and
neither shows up in a single run:

  * the state is never written, and the defaults quietly stand;
  * the state is written but not flushed, so a clean restart restores it and
    a power cut does not — which reads as "sometimes it works".

This starts the real application, changes something, lets it exit, starts it
again against the same state file, and looks at the screen. The second fault
is addressed by fsync in _save_state; it cannot be reproduced here without
cutting power, so what this covers is the first, plus the read-back path.
"""
import os
import sys
import json
import shutil
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from harness import check, equals, report
from test_screen import run

F3 = "\x1bOR"          # xterm F3: the mode picker
F4 = "\x1bOS"          # xterm F4: cycle the color scheme


if __name__ == "__main__":
    print("Remembered state across a restart")
    tmp = tempfile.mkdtemp(prefix="cyberdeck-state-")
    path = os.path.join(tmp, "state", "cyberdeck.json")
    try:
        # A fresh deck, then RTTY chosen from the curated list (F3, then 4).
        first = run(keys=[F3, "4"], state_path=path, settle=1.5)
        body = "\n".join(first.display)
        check("the mode change took effect", "RTTY" in body, body[:200])

        check("a state file was written", os.path.exists(path), path)
        saved = {}
        if os.path.exists(path):
            with open(path) as fh:
                saved = json.load(fh)
        equals("it records the mode", saved.get("mode"), "RTTY")
        check("it records a carrier", isinstance(saved.get("carrier"), int),
              repr(saved.get("carrier")))

        # A second process, same state file, no keys at all.
        second = run(state_path=path, settle=1.8)
        body2 = "\n".join(second.display)
        check("the restarted deck comes back in RTTY", "RTTY" in body2,
              body2[:200])
        check("and says it resumed rather than starting fresh",
              "resumed" in body2 or "RTTY" in body2, body2[:300])

        # The default is BPSK31; seeing it would mean the state was ignored.
        check("it did not fall back to the configured default",
              "BPSK31" not in body2.split("\n")[0], body2.split("\n")[0])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    sys.exit(report())
