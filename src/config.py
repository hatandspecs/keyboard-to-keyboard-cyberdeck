"""Station settings, read from cyberdeck.conf.

The same `KEY = value` form as the iGate project's configuration, so the two
read alike: blank lines and `#` comments ignored, values trimmed, unknown keys
refused rather than silently absorbed. An unknown key is almost always a typo,
and a typo that is ignored becomes a setting that mysteriously does nothing.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Two layouts have to work. On the deck the modules are installed flat into
# /opt/cyberdeck alongside cyberdeck.conf, so the file sits next to this one.
# In the repository the modules are in src/ and the configuration is at the
# project root, one level up. Checking both keeps a single code path for the
# running deck and for anything driven from a checkout.
_CANDIDATES = (
    os.path.join(HERE, "cyberdeck.conf"),
    os.path.join(os.path.dirname(HERE), "cyberdeck.conf"),
)
DEFAULT_PATH = next((c for c in _CANDIDATES if os.path.exists(c)), _CANDIDATES[0])

# key -> (default, converter, description)
SCHEMA = {
    "CALLSIGN":        ("", str, "this station's callsign"),
    "NAME":            ("", str, "operator name, for macros"),
    "QTH":             ("", str, "location, for macros"),
    "LOCATOR":         ("", str, "Maidenhead grid square"),
    "RIG":             ("", str, "radio, for memories: {rig}"),
    "RIG_BANDS":       ("", str, "bands this radio covers, comma separated, "
                                 "e.g. '80 m, 40 m, 20 m'. Empty means all of "
                                 "them — the FTX-1 covers every band listed"),

    "DEFAULT_MODE":    ("BPSK31", str, "modem selected at startup"),
    "DEFAULT_CARRIER": (1500, int, "audio carrier parked here, in Hz"),
    "COLOR":          ("matrix", str, "matrix | deckard | hal | tron"),
    "FONT":            ("12x24", str, "console font; sets the character grid"),

    "FLDIGI_URL":      ("http://127.0.0.1:7362/", str, "fldigi's XML-RPC address"),
    "POLL_MS":         (200, int, "how often to ask fldigi for new text"),
    "SCROLLBACK":      (2000, int, "transcript lines kept in memory"),
    "TX_TIMEOUT":      (180, int, "seconds before an over is aborted; 0 disables"),
    "TIMESTAMPS":      ("yes", str, "yes | no"),
    "INHIBIT_ON_START": ("yes", str, "yes | no — start with transmit inhibited"),
    "RIG_MODE":        ("PKTUSB", str, "rig mode set at startup and on band "
                                       "change; PKTUSB is the radio's data "
                                       "mode, USB is plain sideband, blank "
                                       "leaves the radio alone"),
    "RSID_ON_START":   ("yes", str, "yes | no — follow other stations' mode "
                                    "identifiers automatically"),
    "REMEMBER_STATE":  ("yes", str, "yes | no — restore mode, carrier, color "
                                    "and timestamps across restarts"),
    "STATE_PATH":      ("~/.local/state/cyberdeck.json", str,
                        "where that is kept; delete it to start clean"),

    # Message memories, inserted at the cursor by F5-F12. {call}, {name},
    # {qth}, {grid} and {rig} are replaced from the station settings above, so
    # a memory does not have to be rewritten when the callsign changes.
    # Memories edited on the deck are written to STATE_PATH and override these.
    "MEMORY_5":  ("CQ CQ CQ DE {call} {call} {call} PSE K", str, "F5"),
    "MEMORY_6":  ("DE {call} {call} K", str, "F6"),
    "MEMORY_7":  ("NAME HR IS {name} {name}, QTH {qth} {qth}. HW? BTU", str, "F7"),
    "MEMORY_8":  ("RIG IS {rig} RUNNING 5 W TO A WIRE. ", str, "F8"),
    "MEMORY_9":  ("TNX FB QSO. 73 ES GD DX. DE {call} SK", str, "F9"),
    "MEMORY_10": ("", str, "F10"),
    "MEMORY_11": ("", str, "F11"),
    "MEMORY_12": ("", str, "F12"),
}

COLORS = ("matrix", "deckard", "hal", "tron")


class ConfigError(Exception):
    pass


# Settings renamed since a config file may have been written. Accepting the
# old spelling costs one lookup; refusing it would stop the terminal from
# starting at all, since an unknown key is an error — and a deck that will not
# boot because a file says COLOUR is a poor trade for consistency.
ALIASES = {
    "COLOUR": "COLOR",
}


def load(path=None):
    """Return a dict of settings. A missing file is not an error: the
    defaults describe a usable station that simply has no callsign yet, and
    refusing to start over a missing file would be unhelpful on a first run."""
    path = path or DEFAULT_PATH
    values = {k: v[0] for k, v in SCHEMA.items()}
    if not os.path.exists(path):
        return values

    unknown = []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if "=" not in line:
                raise ConfigError(f"{path}:{lineno}: expected KEY = value")
            key, _, value = line.partition("=")
            key, value = key.strip().upper(), value.strip()
            key = ALIASES.get(key, key)
            if key not in SCHEMA:
                unknown.append(f"{path}:{lineno}: unknown setting '{key}'")
                continue
            converter = SCHEMA[key][1]
            try:
                values[key] = converter(value)
            except ValueError:
                raise ConfigError(
                    f"{path}:{lineno}: {key} = '{value}' is not a "
                    f"{converter.__name__}") from None

    if unknown:
        raise ConfigError("\n".join(unknown))

    validate(values)
    return values


def validate(values):
    if values["COLOR"].lower() not in COLORS:
        raise ConfigError(
            f"COLOR = '{values['COLOR']}' is not one of: {', '.join(COLORS)}")
    values["COLOR"] = values["COLOR"].lower()

    if not 100 <= values["DEFAULT_CARRIER"] <= 4000:
        raise ConfigError(
            f"DEFAULT_CARRIER = {values['DEFAULT_CARRIER']} is outside any SSB "
            "passband; use something like 1500")

    if not 50 <= values["POLL_MS"] <= 5000:
        raise ConfigError(f"POLL_MS = {values['POLL_MS']} is not sensible")

    if values["TX_TIMEOUT"] < 0 or values["TX_TIMEOUT"] > 3600:
        raise ConfigError("TX_TIMEOUT must be 0 (disabled) to 3600 seconds")

    if values["SCROLLBACK"] < 100:
        raise ConfigError("SCROLLBACK below 100 lines is not worth keeping")

    if values["TIMESTAMPS"].lower() not in ("yes", "no"):
        raise ConfigError("TIMESTAMPS must be yes or no")
    values["TIMESTAMPS"] = values["TIMESTAMPS"].lower()
    return values
