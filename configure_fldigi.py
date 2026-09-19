#!/usr/bin/env python3
"""Set fldigi's configuration for the deck, without its GUI.

fldigi is configured through a dialog, and the deck has no pointer and often no
screen. Everything that has to be right for the deck lives in a handful of keys
in fldigi_def.xml, so they are set here instead.

Two settings matter beyond the obvious:

* **Rig control goes through rigctld, not straight to the radio.** The FTX-1
  presents CAT and PTT on two separate serial ports, and fldigi's hamlib
  configuration has room for one. rigctld bridges both and fldigi talks to it
  as "Hamlib NET rigctl" — hamlib model 2 — on localhost:4532. Pointing fldigi
  at the CAT port directly means it and rigctld fight over the same device.
* **Audio must name the radio's codec**, not "default". fldigi uses PortAudio,
  whose device names are not ALSA's; list them with --list-audio on the machine
  the radio is attached to.

    python3 configure_fldigi.py --show
    python3 configure_fldigi.py --list-audio
    python3 configure_fldigi.py --rigctld --audio "USB Audio Device"
"""

import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(HERE, "fldigi-config")

NET_RIGCTL_MODEL = 2          # hamlib RIG_MODEL_NETRIGCTL
NET_RIGCTL_DEVICE = "localhost:4532"

INTERESTING = [
    "MYCALL", "MYNAME", "MYQTH", "MYLOC",
    "AUDIOIO", "PORTINDEVICE", "PORTOUTDEVICE",
    "CHKUSEHAMLIBIS", "HAMRIGMODEL", "HAMRIGDEVICE", "HAMRIGBAUDRATE",
    "HAMLIBPTTONDATA", "XMLRPC_RIG",
]


def path_for(config_dir):
    p = os.path.join(config_dir, "fldigi_def.xml")
    if not os.path.exists(p):
        sys.exit(f"no fldigi_def.xml in {config_dir}. Run ./dev-fldigi.sh once first.")
    return p


def get(text, key):
    m = re.search(rf"<{key}>(.*?)</{key}>", text, re.S)
    return m.group(1) if m else None


def put(text, key, value):
    """Replace a key's value, or report that fldigi has no such key.

    Keys are not invented: a setting fldigi does not know is a setting fldigi
    will ignore, and silently writing one would look like it had worked.
    """
    if re.search(rf"<{key}>.*?</{key}>", text, re.S) is None:
        print(f"  ! {key} is not in this fldigi's configuration; skipped")
        return text, False
    return re.sub(rf"<{key}>.*?</{key}>", f"<{key}>{value}</{key}>", text, count=1, flags=re.S), True


def show(text):
    for key in INTERESTING:
        val = get(text, key)
        if val is not None:
            print(f"  {key:18} {val!r}")


def list_audio():
    try:
        import sounddevice  # noqa
    except ImportError:
        print("The `sounddevice` module is not installed, so PortAudio's device")
        print("names cannot be listed here. On the deck, either:")
        print("  pip install sounddevice      # then rerun with --list-audio")
        print("  or run fldigi over SSH with X forwarding and read the list in")
        print("  its Soundcard configuration.")
        print()
        print("ALSA's view, for reference (fldigi's names usually contain these):")
        # os.system writes straight to the file descriptor while print buffers,
        # so without this the listing appears above its own explanation.
        sys.stdout.flush()
        os.system("arecord -l 2>/dev/null")
        return
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] or d["max_output_channels"]:
            print(f"  [{i}] {d['name']}  in={d['max_input_channels']} out={d['max_output_channels']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config-dir", default=DEFAULT_DIR)
    ap.add_argument("--show", action="store_true", help="print the settings that matter")
    ap.add_argument("--list-audio", action="store_true", help="list PortAudio device names")
    ap.add_argument("--rigctld", action="store_true",
                    help="point rig control at rigctld on localhost:4532")
    ap.add_argument("--no-rig", action="store_true", help="disable rig control entirely")
    ap.add_argument("--audio", metavar="NAME", help="PortAudio device for input and output")
    ap.add_argument("--call", help="set MYCALL")
    args = ap.parse_args()

    if args.list_audio:
        list_audio(); return 0

    path = path_for(args.config_dir)
    text = io_read(path)

    if args.show or not any((args.rigctld, args.no_rig, args.audio, args.call)):
        print(f"{path}:"); show(text); return 0

    changed = []
    if args.rigctld:
        for k, v in (("CHKUSEHAMLIBIS", 1), ("HAMRIGMODEL", NET_RIGCTL_MODEL),
                     ("HAMRIGDEVICE", NET_RIGCTL_DEVICE),
                     ("CHKUSERIGCATIS", 0), ("CHKUSEXMLRPCIS", 0)):
            text, ok = put(text, k, v)
            ok and changed.append(f"{k}={v}")
    if args.no_rig:
        for k in ("CHKUSEHAMLIBIS", "CHKUSERIGCATIS", "CHKUSEXMLRPCIS"):
            text, ok = put(text, k, 0)
            ok and changed.append(f"{k}=0")
    if args.audio:
        for k in ("PORTINDEVICE", "PORTOUTDEVICE"):
            text, ok = put(text, k, args.audio)
            ok and changed.append(f"{k}={args.audio!r}")
        text, ok = put(text, "AUDIOIO", 1)      # PortAudio
        ok and changed.append("AUDIOIO=1 (PortAudio)")
    if args.call:
        text, ok = put(text, "MYCALL", args.call)
        ok and changed.append(f"MYCALL={args.call}")

    if not changed:
        print("nothing to change"); return 0

    shutil.copy2(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{path}  (previous kept as fldigi_def.xml.bak)")
    for c in changed:
        print(f"  set {c}")
    print("\nRestart fldigi for these to take effect.")
    return 0


def io_read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


if __name__ == "__main__":
    sys.exit(main())
