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
DEFAULT_DIR = os.path.join(os.path.dirname(HERE), "fldigi-config")

NET_RIGCTL_MODEL = 2          # hamlib RIG_MODEL_NETRIGCTL
NET_RIGCTL_DEVICE = "localhost:4532"

INTERESTING = [
    "MYCALL", "MYNAME", "MYQTH", "MYLOC",
    "AUDIOIO", "PORTINDEVICE", "PORTOUTDEVICE",
    "CHKUSEHAMLIBIS", "HAMRIGMODEL", "HAMRIGDEVICE", "HAMRIGBAUDRATE",
    "HAMLIBPTTONDATA", "XMLRPC_RIG",
    # Carrier behaviour on a mode change, and the RSID settings that interact
    # with it. See --keep-carrier.
    "STARTATSWEETSPOT", "PSKSWEETSPOT", "DISABLERSIDFREQCHANGE",
    "RECEIVERSID", "TRANSMITRSID",
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


def pick_audio(pattern="USB Audio"):
    """Choose the PortAudio device this machine should use for the radio.

    Prefer the direct hardware device (``hw:``): it reaches the codec without a
    sound server resampling in the middle, which is what a modem wants. Fall
    back to a sound-server device only when no hardware device matched at all.

    The name still cannot be seeded once and reused, because the ``hw:`` index
    is assigned in enumeration order and the deck may number the radio
    differently than the build machine does. Run this on each machine.

    A device that is *open elsewhere* reports zero input channels rather than
    an error, so a matching hardware device with no input is treated as busy
    and refused. Silently falling through to the sound-server device would
    write a working-looking configuration that decodes nothing.
    """
    try:
        import sounddevice as sd
    except ImportError:
        return None, "the sounddevice module is not installed"

    matches = [d for d in sd.query_devices() if pattern.lower() in d["name"].lower()]
    if not matches:
        return None, f"no audio device whose name contains {pattern!r}"

    hw = [d for d in matches if "hw:" in d["name"]]
    busy = [d for d in hw if d["max_input_channels"] == 0]
    if busy and not [d for d in hw if d["max_input_channels"] > 0]:
        names = ", ".join(repr(d["name"]) for d in busy)
        return None, (f"{names} reports no input channel, which means another "
                      "program holds the capture side — stop fldigi "
                      "(./dev-fldigi.sh stop) and try again")

    usable = [d for d in matches if d["max_input_channels"] > 0]
    if not usable:
        names = ", ".join(repr(d["name"]) for d in matches)
        return None, (f"devices matched ({names}) but none reports an input "
                      "channel — another program may hold the capture side")
    chosen = ([d for d in usable if "hw:" in d["name"]] or usable)[0]
    return chosen["name"], None


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
    ap.add_argument("--auto-audio", metavar="PATTERN", nargs="?", const="USB Audio",
                    help="pick the audio device on this machine by name pattern "
                         "(default 'USB Audio'); use on the deck itself")
    ap.add_argument("--call", help="set MYCALL")
    ap.add_argument("--keep-carrier", action="store_true",
                    help="nothing but the operator moves the carrier: no sweet-spot "
                         "reset on a mode change, and no retune on a received RSID "
                         "(STARTATSWEETSPOT=0, DISABLERSIDFREQCHANGE=1)")
    args = ap.parse_args()

    if args.list_audio:
        list_audio(); return 0

    path = path_for(args.config_dir)
    text = io_read(path)

    if args.auto_audio:
        name, why = pick_audio(args.auto_audio)
        if name is None:
            print(f"could not choose an audio device: {why}", file=sys.stderr)
            return 1
        print(f"  chose {name!r}")
        args.audio = name

    if args.show or not any((args.rigctld, args.no_rig, args.audio, args.call,
                            args.keep_carrier)):
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
    if args.keep_carrier:
        # The carrier is the operator's. Two fldigi behaviors move it without
        # being asked, and both are turned off together because the intent is
        # one thing: what is tuned stays tuned until a key says otherwise.
        #
        #   STARTATSWEETSPOT     every new modem starts at the sweet spot —
        #                        1500 Hz for PSK, RTTY and CW alike — so any
        #                        mode change resets the carrier.
        #   DISABLERSIDFREQCHANGE  a received RSID retunes to wherever the
        #                        identifier was heard.
        #
        # The first was observed on the air in both directions between two
        # stations: change mode at 700 Hz and the other end jumps to 1500. The
        # second is the remaining way a correspondent can move your carrier,
        # and is left disabled for the same reason — searching and nudging are
        # deliberate acts, and a signal arriving should not undo them.
        for key, value, why in (
                ("STARTATSWEETSPOT", 0, "no sweet-spot reset on a mode change"),
                ("DISABLERSIDFREQCHANGE", 1, "a received RSID cannot retune")):
            text, ok = put(text, key, value)
            ok and changed.append(f"{key}={value} ({why})")

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
