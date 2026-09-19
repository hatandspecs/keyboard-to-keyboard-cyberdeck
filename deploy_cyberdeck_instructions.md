# Deploying the Cyberdeck — Runbook

Blank SD card to a working terminal, in order. Every command is meant to be
run as written.

**Before starting, read this once:** `build_deck_image.sh build` has never been
run end to end. It was written against a machine with no loop devices, no sudo
and no network. The generated units and scripts are all tested, and the
mount-and-write path follows the approach proven in the iGate project — but
expect to hit something. Phase 6 covers recovery.

**Two known risks, both flagged at the point they bite:** the DSI panel overlay
(Phase 0, step 4) and fldigi's audio device on the Pi (Phase 4, step 3).

---

## Phase 0 — on the laptop

Everything here happens before the card is touched.

### 1. Find the Bluetooth keyboard's address

Put the keyboard in pairing mode — usually holding a channel or pairing key
until its LED blinks rapidly. A keyboard that is merely switched on and
connected elsewhere will not advertise.

```bash
bluetoothctl
```

```
scan on
# wait for a [NEW] Device line with the keyboard's name
devices
scan off
quit
```

Already found for this deck:

```
DF:3C:77:61:6C:21  Pebble K380s
```

That address begins `DF`, which makes it a **static random** Bluetooth LE
address: stable between scans, so pairing by address works. It changes only if
the keyboard is factory reset — rescan and update `deck.conf` if that happens.

### 2. Configure fldigi for the deck

Plug the **FTX-1** into the laptop first. This step decides what the card is
seeded with, and fldigi cannot be configured on the deck without a screen.

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
./dev-fldigi.sh                             # Xvfb + fldigi, seeded from ~/.fldigi
python3 configure_fldigi.py --show          # what is set now
```

Find the radio's codec as PortAudio names it:

```bash
pip install sounddevice                     # only needed for the listing
python3 configure_fldigi.py --list-audio
```

Then set both things that matter:

```bash
python3 configure_fldigi.py --rigctld --audio "<the FTX-1 codec name>"
python3 configure_fldigi.py --show          # confirm
```

Expect to see:

```
CHKUSEHAMLIBIS     '1'
HAMRIGMODEL        '2'
HAMRIGDEVICE       'localhost:4532'
PORTINDEVICE       '<the codec>'
```

**Why `--rigctld` and not hamlib directly.** The FTX-1 presents CAT on one
serial port and PTT on another; fldigi's hamlib configuration has room for one
port. `rigctld` bridges both and fldigi connects to it over loopback as *Hamlib
NET rigctl*. Pointing fldigi straight at the CAT port means it and the deck's
`rigctld` service fight over the same device.

The previous configuration is kept as `fldigi-config/fldigi_def.xml.bak`.

### 3. Fill in the two configuration files

```bash
cp deck.secrets.example deck.secrets
$EDITOR deck.secrets        # DECK_USER_PASSWORD, DECK_WIFI_SSID_1, DECK_WIFI_PSK_1
$EDITOR cyberdeck.conf      # CALLSIGN, NAME, QTH, LOCATOR
```

`DECK_SSH_PUBKEY = ~/.ssh/id_ed25519.pub` in `deck.secrets` saves typing a
password on every login later.

`deck.secrets` is gitignored. Both the image and the finished card contain
these credentials in recoverable form — Raspberry Pi OS has no disk encryption
and the card pulls out with a fingernail.

### 4. Set the panel overlay ⚠️

`deck.conf` ships with `DECK_PANEL_OVERLAY = vc4-kms-dsi-7inch`, which is the
**official 7-inch panel**. A Waveshare 5" DSI almost certainly wants something
else; recent kernels use a form like:

```
DECK_PANEL_OVERLAY = vc4-kms-dsi-waveshare-panel,5_0_inch
```

Check the panel's own documentation. **A wrong overlay means a blank screen and
nothing else can be tested**, so it is worth five minutes now rather than an
hour of SSH debugging later.

---

## Phase 1 — build the image

```bash
./build_deck_image.sh check
```

It refuses until both configuration files are real, and prints a summary:
hostname, user, variant, keyboard, panel, and each WiFi network. Read that
summary — it is the last chance to catch a typo cheaply.

Review what will be written to the card:

```bash
./build_deck_image.sh units
less deck-build/units/cyberdeck-ui.service
less deck-build/units/cyberdeck-firstboot.sh
```

Then build. This downloads about 500 MB the first time and asks for `sudo`:

```bash
./build_deck_image.sh build
```

It ends with the path to `deck-build/cyberdeck.img`.

---

## Phase 2 — flash the card

```bash
lsblk
```

Identify the card by size. **Read it twice.** The next command overwrites the
device completely.

```bash
./build_deck_image.sh flash /dev/sdX
sync
```

`/dev/sdX` is not a real device — substitute what `lsblk` showed. The script
asks you to type the path a second time to confirm, and refuses a device with
mounted partitions.

---

## Phase 3 — first boot

1. **Put the keyboard in pairing mode.**
2. Card into the Pi.
3. Panel ribbon connected.
4. FTX-1 into the single USB port.
5. Power last.

Allow **five to ten minutes**. The Pi joins WiFi and installs fldigi, Xvfb,
hamlib, Python, console fonts and bluez over the network. The screen stays
blank until the terminal appears — that is the quiet boot working, not a fault.

Then, from the laptop:

```bash
ssh deck@cyberdeck.local
```

```bash
systemctl status cyberdeck-firstboot --no-pager
journalctl -u cyberdeck-firstboot -n 40 --no-pager
systemctl status cyberdeck-xvfb cyberdeck-fldigi cyberdeck-ui --no-pager
```

Keyboard:

```bash
bluetoothctl info DF:3C:77:61:6C:21 | grep -E 'Connected|Paired'
journalctl -u cyberdeck-btpair -n 20 --no-pager
```

If it did not pair, put it back in pairing mode and wait — `cyberdeck-btpair.timer`
retries every five minutes rather than giving up. To force an attempt:

```bash
sudo systemctl start cyberdeck-btpair
```

---

## Phase 4 — the radio

### 1. Devices

```bash
ls -l /dev/ttyUSB* /dev/ttyACM*     # CAT and PTT
arecord -l                          # the FTX-1's codec and its card number
systemctl status cyberdeck-rigctld --no-pager
```

### 2. Is fldigi answering?

```bash
python3 -c "
import sys; sys.path.insert(0,'/opt/cyberdeck')
from fldigi_client import Fldigi
f = Fldigi()
print('connected:', f.connected, '|', f.version())
print('modem :', f.modem(), '| carrier', f.carrier(), 'Hz')
print('rig   :', f.frequency(), f.rig_mode())"
```

A frequency of `0.0` means rig control is not working — check
`cyberdeck-rigctld` and that fldigi is set to `localhost:4532`.

### 3. Audio device ⚠️

If `arecord -l` gives the FTX-1 a **different card number than the laptop did**,
the seeded configuration names the wrong device and the deck will decode
nothing while looking perfectly healthy.

```bash
cd /opt/cyberdeck
python3 configure_fldigi.py --config-dir /opt/cyberdeck/fldigi-config --show
python3 configure_fldigi.py --config-dir /opt/cyberdeck/fldigi-config \
  --audio "<the name on this machine>"
sudo systemctl restart cyberdeck-fldigi
```

If the name is hard to determine, run fldigi's own dialog over SSH — it runs on
the Pi and displays on the laptop:

```bash
ssh -X deck@cyberdeck.local
sudo systemctl stop cyberdeck-fldigi
fldigi --config-dir /opt/cyberdeck/fldigi-config
# set the sound card, quit
sudo systemctl start cyberdeck-fldigi
```

---

## Phase 5 — on the air

At the deck's own screen and keyboard:

1. `F3` → pick **BPSK31**.
2. `F2` → `s` to **turn the squelch on**. With it open, fldigi decodes the noise
   floor continuously and the transcript fills with random characters within
   seconds.
3. Tune the FTX-1 to **14.070 USB**.
4. Watch for decoded text.

Before transmitting:

* **Set the radio's time-out timer.** PTT is a pin the interface holds; a hung
  host holds the radio keyed, and the radio's own timer is the only backstop.
* Check that `Ctrl-C` aborts, before relying on it.

To work someone: type while receiving, `Ctrl-T` to start the over, `Ctrl-K` to
hand back. `Enter` inserts a newline — it does not send.

---

## Phase 6 — when something fails

### The build stopped partway

It leaves the image mounted on a loop device.

```bash
mount | grep /tmp/tmp
sudo umount /tmp/tmp.XXXX /tmp/tmp.YYYY
losetup -a
sudo losetup -d /dev/loopN
```

Then rerun `./build_deck_image.sh build`. The downloaded image is cached, so
only the customisation repeats.

### Blank panel, but SSH works

Almost certainly the overlay (Phase 0, step 4).

```bash
grep dtoverlay /boot/firmware/config.txt
sudo nano /boot/firmware/config.txt      # correct it
sudo reboot
```

Check the terminal itself is running with `systemctl status cyberdeck-ui`.

### The terminal is not running

```bash
journalctl -u cyberdeck-ui -n 40 --no-pager
journalctl -u cyberdeck-fldigi -n 40 --no-pager
```

`cyberdeck-ui` requires `cyberdeck-fldigi`, which requires `cyberdeck-xvfb`.
Check them in that order.

### No keyboard, no screen, no SSH

The one USB port holds the radio. Unplug the FTX-1, plug in a USB keyboard, and
work at the console. That is the recovery path, and it is the reason the build
refuses a placeholder Bluetooth address.

### Start again

Reflash. Nothing on the card is precious; everything that describes this deck
lives in `deck.conf`, `deck.secrets` and `cyberdeck.conf` on the laptop.

---

## What has not been tested

Recorded honestly so that a failure here is recognised rather than debugged
from first principles:

| | |
|---|---|
| `build_deck_image.sh build` | Written, never run end to end |
| The 5" DSI panel on a Pi 3A+ | Never attached; overlay and power source unconfirmed |
| Bluetooth pairing at first boot | The script is syntax-checked, never run against a real keyboard |
| Terminus console fonts at 12×24 | Never rendered on the panel |
| fldigi on a 3A+'s 512 MB | Runs comfortably on a laptop; untested with Xvfb on that board |

Everything above the hardware line — the terminal, the modes, the menus, the
over model, the colour schemes — is covered by 113 tests against a live fldigi.
