"""Direct CAT to the radio, through rigctld.

Why this exists
---------------
Hamlib 4.6.2 — the version in Raspberry Pi OS Trixie — builds a malformed
frequency command for the FT-991 model, which is the closest model that reads
the FTX-1 correctly. From a live trace on the deck:

    newcat_set_freq: is_ft991=1, CACHE(rig)->split=0, vfo=VFOA
    newcat_set_freq:1388 cmd_str = FA14075000;

That is ``FA`` plus **eight** digits. The FTX-1 CAT manual (p.16) specifies
nine, zero-padded, and the radio's own replies use nine:

    ret_data = FA014070000;

An eight-digit command is silently discarded — no error, no change, and the
deck's display snaps back to the radio's real frequency a moment later, which
looks exactly like the deck fighting the radio. Writing the documented form by
hand moves the VFO immediately:

    printf 'FA014075000;' > /dev/ttyUSB0      # confirmed on the deck

The same fault blocks every frequency path: the band presets, the tuning
screen's VFO keys, and anything fldigi tries to do through hamlib.

Rather than take the serial port away from rigctld — which also carries PTT,
and which fldigi needs — this sends the correct bytes *through* it. rigctld's
``w`` (send_cmd) forwards a raw string to the rig, so there is still exactly
one owner of the port.

This is a workaround for a bug in one hamlib version, not a better design. If
the deck is ever on a hamlib that formats the command properly, CAT_VFO can be
turned off in cyberdeck.conf and fldigi's own rig control does the job.
"""
import socket


class Rigctld:
    """A small client for rigctld's text protocol on localhost."""

    def __init__(self, host="127.0.0.1", port=4532, timeout=2.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.last_error = ""

    def _talk(self, line, expect_reply=True):
        """Send one command. Returns the reply text, or None on failure.

        Never raises: the deck has to keep running with the radio unplugged,
        and a failed frequency change is a note on screen, not a crash.
        """
        try:
            with socket.create_connection((self.host, self.port), self.timeout) as s:
                s.sendall((line + "\n").encode("ascii"))
                if not expect_reply:
                    return ""
                s.settimeout(self.timeout)
                try:
                    return s.recv(4096).decode("ascii", "replace").strip()
                except socket.timeout:
                    # A Yaesu set command produces no reply. Silence here is
                    # success, not a fault.
                    return ""
        except OSError as exc:
            self.last_error = str(exc)
            return None

    @property
    def connected(self):
        return self._talk("f") is not None

    def send_cat(self, command):
        """Forward a raw CAT string such as 'FA014075000;' to the radio."""
        return self._talk(f"w {command}", expect_reply=False) is not None

    def set_frequency(self, hz):
        """Set the MAIN VFO using the FTX-1's documented nine-digit form."""
        hz = int(round(float(hz)))
        if hz <= 0:
            return False
        return self.send_cat(f"FA{hz:09d};")

    def frequency(self):
        """The radio's frequency in Hz, or 0.0 if it cannot be read.

        Reads go through hamlib normally — it is only the set path that is
        broken — so this uses rigctld's own 'f' rather than another raw
        command.
        """
        reply = self._talk("f")
        if not reply:
            return 0.0
        for line in reply.splitlines():
            line = line.strip()
            if line.lstrip("-").isdigit():
                return float(line)
        return 0.0
