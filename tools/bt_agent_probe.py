#!/usr/bin/env python3
"""Prove a BlueZ pairing agent can be registered and survive a scan.

Run this ON THE DECK, as the `deck` user, with no sudo. It answers the one
question that has to be settled before a pairing interface is worth writing,
and it answers it in isolation so that a failure is unambiguous.

    python3 bt_agent_probe.py            # register, scan 15s, list, unregister
    python3 bt_agent_probe.py --seconds 30

Why this exists rather than going straight to the interface:

The original pairing script ran each `bluetoothctl` command as its own
process. Each invocation registered an agent, and that agent died when the
process exited — so pairing was attempted with no agent present, BlueZ had
nowhere to send the passkey, and the script reported success on a keyboard
that could not type a character. The same lifetime rule was demonstrated
again from the command line on 2026-09-22: `StartDiscovery` in one `busctl`
call, then `StopDiscovery` in another, fails with "No discovery started",
because BlueZ tracks discovery per D-Bus connection and the first call's
connection was already gone.

So the property to establish is not "can this user talk to BlueZ" — that is
already known — but "can ONE connection hold an agent registered while
discovery runs and devices appear". That is what the real interface will do,
and it is what this does, with nothing else in the way.

What a pass looks like:

    agent registered as /org/cyberdeck/agent
    discovery started
      DC:2C:26:... Pebble Keys ...        (an LE HID device, if one is awake)
    discovery stopped
    agent still registered after the scan: yes
    agent unregistered

`agent still registered after the scan` is the line that matters. If the agent
is gone, an in-process connection is not enough and pairing needs a service
that outlives the terminal — a much larger change.

This registers an agent; it does NOT pair anything. No bond is created, no
device is touched, and nothing is written. It is safe to run on a working
deck, including one with a keyboard already bonded.
"""
import argparse
import sys

AGENT_PATH = "/org/cyberdeck/agent"
# KeyboardDisplay, not NoInputNoOutput: an LE keyboard's bond requires a
# passkey shown by the host and typed on the keyboard being paired. That is
# why the capability matters and why pairing cannot be made silent.
CAPABILITY = "KeyboardDisplay"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=int, default=15,
                    help="how long to scan (default 15)")
    ap.add_argument("--adapter", default="/org/bluez/hci0")
    args = ap.parse_args()

    try:
        import gi
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError) as exc:
        print(f"python3-gi is not available: {exc}", file=sys.stderr)
        print("On the deck:  sudo apt install -y python3-gi", file=sys.stderr)
        return 2

    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    print("system bus: connected")

    # The agent has to answer method calls, so it is exported on this
    # connection. An agent that is merely *named* to BlueZ without an object
    # behind it is the same failure as one whose process has exited.
    node = Gio.DBusNodeInfo.new_for_xml("""
    <node>
      <interface name='org.bluez.Agent1'>
        <method name='Release'/>
        <method name='RequestPinCode'>
          <arg type='o' name='device' direction='in'/>
          <arg type='s' name='pincode' direction='out'/>
        </method>
        <method name='DisplayPinCode'>
          <arg type='o' name='device' direction='in'/>
          <arg type='s' name='pincode' direction='in'/>
        </method>
        <method name='RequestPasskey'>
          <arg type='o' name='device' direction='in'/>
          <arg type='u' name='passkey' direction='out'/>
        </method>
        <method name='DisplayPasskey'>
          <arg type='o' name='device' direction='in'/>
          <arg type='u' name='passkey' direction='in'/>
          <arg type='q' name='entered' direction='in'/>
        </method>
        <method name='RequestConfirmation'>
          <arg type='o' name='device' direction='in'/>
          <arg type='u' name='passkey' direction='in'/>
        </method>
        <method name='RequestAuthorization'>
          <arg type='o' name='device' direction='in'/>
        </method>
        <method name='AuthorizeService'>
          <arg type='o' name='device' direction='in'/>
          <arg type='s' name='uuid' direction='in'/>
        </method>
        <method name='Cancel'/>
      </interface>
    </node>""")

    seen_calls = []

    def on_call(_conn, _sender, _path, _iface, method, params, invocation):
        seen_calls.append(method)
        print(f"  agent called: {method}{params.unpack() if params else ''}")
        # This probe pairs nothing, so every request is declined politely.
        if method in ("RequestPinCode",):
            invocation.return_value(GLib.Variant("(s)", ("0000",)))
        elif method in ("RequestPasskey",):
            invocation.return_value(GLib.Variant("(u)", (0,)))
        else:
            invocation.return_value(None)

    # register_object is deprecated in newer PyGObject and the replacement is
    # absent in older ones. The deck runs Debian's build and this laptop runs
    # Fedora's; prefer whatever is present rather than pinning either.
    register = getattr(bus, "register_object_with_closures2", None) \
        or getattr(bus, "register_object_with_closures", None) \
        or bus.register_object
    reg_id = register(AGENT_PATH, node.interfaces[0], on_call, None, None)
    if not reg_id:
        print("could not export the agent object", file=sys.stderr)
        return 1
    print(f"agent object exported at {AGENT_PATH}")

    def bluez(path, iface, method, params=None, reply="()"):
        return bus.call_sync("org.bluez", path, iface, method, params,
                             GLib.VariantType.new(reply),
                             Gio.DBusCallFlags.NONE, 10000, None)

    try:
        bluez("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
              GLib.Variant("(os)", (AGENT_PATH, CAPABILITY)))
        print(f"agent registered as {AGENT_PATH}, capability {CAPABILITY}")
    except GLib.Error as exc:
        print(f"RegisterAgent FAILED: {exc.message}", file=sys.stderr)
        print("\nThis is the answer the probe exists to get: an in-process",
              file=sys.stderr)
        print("agent is not permitted, and pairing needs another approach.",
              file=sys.stderr)
        return 1

    try:
        bluez(args.adapter, "org.bluez.Adapter1", "StartDiscovery")
        print("discovery started")
    except GLib.Error as exc:
        print(f"StartDiscovery failed: {exc.message}", file=sys.stderr)

    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(args.seconds, lambda: (loop.quit(), False)[1])
    print(f"scanning for {args.seconds}s — put a keyboard into pairing mode now")
    loop.run()

    try:
        bluez(args.adapter, "org.bluez.Adapter1", "StopDiscovery")
        print("discovery stopped")
    except GLib.Error as exc:
        print(f"StopDiscovery failed: {exc.message}")

    # What the scan found, so the interface knows what it will have to show.
    try:
        managed = bus.call_sync(
            "org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
            "GetManagedObjects", None, GLib.VariantType.new("(a{oa{sa{sv}}})"),
            Gio.DBusCallFlags.NONE, 10000, None).unpack()[0]
    except GLib.Error as exc:
        managed = {}
        print(f"GetManagedObjects failed: {exc.message}", file=sys.stderr)

    devices = []
    for path, ifaces in managed.items():
        dev = ifaces.get("org.bluez.Device1")
        if not dev:
            continue
        devices.append((dev.get("Address", "?"), dev.get("Alias", dev.get("Name", "")),
                        dev.get("Paired", False), dev.get("Connected", False),
                        dev.get("Icon", "")))
    print(f"\n{len(devices)} device(s) known to BlueZ:")
    for addr, name, paired, connected, icon in sorted(devices, key=lambda d: d[1] or ""):
        marks = " ".join(m for m, on in
                         (("paired", paired), ("connected", connected)) if on)
        kb = "  <-- looks like a keyboard" if icon == "input-keyboard" else ""
        print(f"  {addr}  {name or '(unnamed)':28} {marks}{kb}")

    # The question this probe exists to answer.
    still = False
    try:
        bluez("/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent",
              GLib.Variant("(o)", (AGENT_PATH,)))
        still = True
    except GLib.Error as exc:
        print(f"\nRequestDefaultAgent failed: {exc.message}")
    print(f"\nagent still registered after the scan: {'YES' if still else 'NO'}")
    if seen_calls:
        print(f"agent methods called during the scan: {', '.join(seen_calls)}")

    try:
        bluez("/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent",
              GLib.Variant("(o)", (AGENT_PATH,)))
        print("agent unregistered")
    except GLib.Error as exc:
        print(f"UnregisterAgent failed: {exc.message}")
    bus.unregister_object(reg_id)
    return 0 if still else 1


if __name__ == "__main__":
    sys.exit(main())
