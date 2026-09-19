#!/usr/bin/env bash
# Build and flash the cyberdeck's SD card.
#
#   ./build_deck_image.sh check           validate deck.conf and deck.secrets
#   ./build_deck_image.sh units [dir]     write the systemd units out for review
#   ./build_deck_image.sh build           produce deck-build/cyberdeck.img
#   ./build_deck_image.sh flash /dev/sdX  write that image to a card
#
# The card is customized offline on this machine, not on the Pi: the image is
# loop-mounted and written into, so the deck boots straight into a working
# terminal with no console session at any point. Same approach as the iGate
# project's build_pi_image.sh, which is where the loop-mount details were
# worked out.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DECK_CONF="${SCRIPT_DIR}/deck.conf"
DECK_SECRETS="${SCRIPT_DIR}/deck.secrets"
BUILD_DIR="${SCRIPT_DIR}/deck-build"
IMAGE_OUT="${BUILD_DIR}/cyberdeck.img"

declare -A CFG=()

RPI_IMAGE_ARMHF="https://downloads.raspberrypi.com/raspios_lite_armhf_latest"
RPI_IMAGE_ARM64="https://downloads.raspberrypi.com/raspios_lite_arm64_latest"

step() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------ config --

load_kv() {  # file
  local file="$1" line key value
  [[ -f "$file" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"; value="${line#*=}"
    key="${key//[[:space:]]/}"
    value="$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' <<<"$value")"
    CFG["$key"]="$value"
  done < "$file"
  return 0
}

validate() {
  load_kv "$DECK_CONF" || die "missing deck.conf"
  load_kv "$DECK_SECRETS" || die "missing deck.secrets — copy deck.secrets.example and fill it in"

  local k
  for k in DECK_HOSTNAME DECK_USER DECK_WIFI_COUNTRY DECK_IMAGE_VARIANT; do
    [[ -n "${CFG[$k]:-}" ]] || die "$k is not set in deck.conf"
  done
  [[ "${CFG[DECK_IMAGE_VARIANT]}" =~ ^(armhf|arm64)$ ]] \
    || die "DECK_IMAGE_VARIANT must be armhf or arm64"

  [[ -n "${CFG[DECK_USER_PASSWORD]:-}" ]] || die "DECK_USER_PASSWORD is not set in deck.secrets"
  [[ "${CFG[DECK_USER_PASSWORD]}" != "change-me" ]] || die "DECK_USER_PASSWORD is still the example value"
  [[ -n "${CFG[DECK_WIFI_SSID_1]:-}" ]] || die "DECK_WIFI_SSID_1 is not set in deck.secrets"
  [[ -n "${CFG[DECK_WIFI_PSK_1]:-}" ]] || die "DECK_WIFI_PSK_1 is not set in deck.secrets"

  # The keyboard is the one part of this that cannot be fixed without a
  # keyboard, so the address is checked rather than discovered at 3am.
  local bt="${CFG[DECK_BT_KEYBOARD]:-}"
  if [[ -n "$bt" ]]; then
    [[ "$bt" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]] \
      || die "DECK_BT_KEYBOARD = '$bt' is not a MAC address like AA:BB:CC:DD:EE:FF"
    [[ "${bt^^}" != "AA:BB:CC:DD:EE:FF" ]] \
      || die "DECK_BT_KEYBOARD is still the example address; run 'bluetoothctl scan on' to find the real one"
  else
    note "DECK_BT_KEYBOARD is blank: the deck will build, but nothing will be"
    note "paired and the only input will be over SSH."
  fi

  [[ -n "${CFG[DECK_PANEL_OVERLAY]:-}" ]] \
    || note "DECK_PANEL_OVERLAY is blank: no DSI overlay will be added to config.txt"

  note "hostname   ${CFG[DECK_HOSTNAME]}   user ${CFG[DECK_USER]}"
  note "variant    ${CFG[DECK_IMAGE_VARIANT]}"
  note "keyboard   ${CFG[DECK_BT_KEYBOARD]:-none} (${CFG[DECK_BT_KEYBOARD_NAME]:-unnamed})"
  note "panel      ${CFG[DECK_PANEL_OVERLAY]:-none}, font ${CFG[DECK_CONSOLE_FONT]:-default}"
  local n=1
  while [[ -n "${CFG[DECK_WIFI_SSID_$n]:-}" ]]; do
    note "wifi       ${CFG[DECK_WIFI_SSID_$n]}"
    n=$((n + 1))
  done
}

require_tools() {
  local t missing=()
  for t in losetup mount umount sudo openssl rsync curl xz dd; do
    command -v "$t" >/dev/null || missing+=("$t")
  done
  ((${#missing[@]} == 0)) || die "missing required tools: ${missing[*]}"
}

# ------------------------------------------------------------- unit files --

# Printed rather than installed, so `units` can show exactly what the card
# will get without mounting anything.
emit_unit() {  # name user dir
  local which="$1" user="$2" dir="$3"
  case "$which" in
    xvfb)
      # Its own unit, not an ExecStartPre on fldigi: ExecStartPre waits for the
      # command to exit, and an X server never does. That would hang the
      # fldigi unit at startup forever, and systemd-analyze does not catch it.
      cat <<EOF
[Unit]
Description=Virtual X server for headless fldigi
Before=cyberdeck-fldigi.service

[Service]
Type=simple
User=${user}
ExecStart=/usr/bin/Xvfb :99 -screen 0 1024x768x16
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
      ;;
    fldigi)
      cat <<EOF
[Unit]
Description=fldigi, headless, for the cyberdeck terminal
After=network.target sound.target cyberdeck-xvfb.service
Requires=cyberdeck-xvfb.service
# fldigi is an FLTK application with no headless mode, so it runs against a
# virtual X server that is never displayed. See design_doc.md section 4.1.

[Service]
Type=simple
User=${user}
WorkingDirectory=${dir}
Environment=DISPLAY=:99
# A seeded configuration directory, not an empty one: fldigi crashes on first
# run against an empty config with an assertion failure in std::string.
ExecStart=/usr/bin/fldigi --config-dir ${dir}/fldigi-config \\
  --xmlrpc-server-address 127.0.0.1 --xmlrpc-server-port 7362
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
      ;;
    rigctld)
      cat <<EOF
[Unit]
Description=hamlib rigctld for the cyberdeck's radio
After=network.target
ConditionPathExists=${CFG[DECK_CAT_DEVICE]:-/dev/ttyUSB0}

[Service]
Type=simple
User=${user}
ExecStart=/usr/bin/rigctld -m ${CFG[DECK_RIG_MODEL]:-1035} \\
  -r ${CFG[DECK_CAT_DEVICE]:-/dev/ttyUSB0} -s ${CFG[DECK_CAT_BAUD]:-38400} \\
  -p ${CFG[DECK_PTT_DEVICE]:-/dev/ttyACM0} -P RIG -t 4532
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
      ;;
    ui)
      cat <<EOF
[Unit]
Description=Cyberdeck terminal on tty1
After=cyberdeck-fldigi.service
Wants=cyberdeck-fldigi.service
Conflicts=getty@tty1.service
# The terminal owns the console: no login prompt, no boot messages, nothing
# else on the screen.

[Service]
Type=simple
User=${user}
WorkingDirectory=${dir}
TTYPath=/dev/tty1
StandardInput=tty
StandardOutput=tty
TTYReset=yes
TTYVHangup=yes
Environment=TERM=linux
ExecStartPre=-/usr/bin/setfont ${CFG[DECK_CONSOLE_FONT]:-Uni3-TerminusBold24x12}
ExecStart=/usr/bin/python3 ${dir}/cyberdeck.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
      ;;
    btpair)
      cat <<EOF
[Unit]
Description=Pair and connect the cyberdeck's Bluetooth keyboard
After=bluetooth.service
Wants=bluetooth.service
ConditionPathExists=!/var/lib/cyberdeck-bt-paired

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/cyberdeck-bt-pair.sh
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
EOF
      ;;
    btpair-timer)
      cat <<'EOF'
[Unit]
Description=Retry Bluetooth keyboard pairing until it succeeds

[Timer]
OnBootSec=3min
OnUnitActiveSec=5min
Unit=cyberdeck-btpair.service

[Install]
WantedBy=timers.target
EOF
      ;;
    *) die "emit_unit: unknown unit '$which'" ;;
  esac
}

emit_bt_script() {
  cat <<EOF
#!/usr/bin/env bash
# Pair and trust the keyboard named in deck.conf.
#
# A headless appliance has no way to run a pairing interface, and the one USB
# port holds the radio, so a keyboard that will not pair leaves no way in
# except SSH. This runs at boot and retries on a timer until it succeeds.
set -uo pipefail

MAC="${CFG[DECK_BT_KEYBOARD]:-}"
NAME="${CFG[DECK_BT_KEYBOARD_NAME]:-keyboard}"
TIMEOUT="${CFG[DECK_BT_PAIR_TIMEOUT]:-120}"
MARKER=/var/lib/cyberdeck-bt-paired

[[ -n "\$MAC" ]] || { echo "no DECK_BT_KEYBOARD configured; nothing to pair"; exit 0; }

echo "Looking for \$NAME (\$MAC) for up to \${TIMEOUT}s..."
bluetoothctl power on >/dev/null 2>&1 || true
bluetoothctl agent NoInputNoOutput >/dev/null 2>&1 || true
bluetoothctl default-agent >/dev/null 2>&1 || true
bluetoothctl --timeout "\$TIMEOUT" scan on >/dev/null 2>&1 || true

for attempt in 1 2 3; do
  bluetoothctl pair "\$MAC"    >/dev/null 2>&1 || true
  bluetoothctl trust "\$MAC"   >/dev/null 2>&1 || true
  bluetoothctl connect "\$MAC" >/dev/null 2>&1 || true
  if bluetoothctl info "\$MAC" 2>/dev/null | grep -q "Connected: yes"; then
    echo "\$NAME connected."
    touch "\$MARKER"
    exit 0
  fi
  echo "  attempt \$attempt did not connect; retrying"
  sleep 5
done

echo "\$NAME not connected. Put it in pairing mode; this retries every 5 minutes."
exit 1
EOF
}

cmd_units() {
  local out="${1:-${BUILD_DIR}/units}"
  load_kv "$DECK_CONF" >/dev/null 2>&1 || true
  local user="${CFG[DECK_USER]:-deck}"
  local dir="/opt/${CFG[DECK_INSTALL_DIR]:-cyberdeck}"
  mkdir -p "$out"
  emit_unit xvfb         "$user" "$dir" > "$out/cyberdeck-xvfb.service"
  emit_unit fldigi       "$user" "$dir" > "$out/cyberdeck-fldigi.service"
  emit_unit rigctld      "$user" "$dir" > "$out/cyberdeck-rigctld.service"
  emit_unit ui           "$user" "$dir" > "$out/cyberdeck-ui.service"
  emit_unit btpair       "$user" "$dir" > "$out/cyberdeck-btpair.service"
  emit_unit btpair-timer "$user" "$dir" > "$out/cyberdeck-btpair.timer"
  emit_bt_script > "$out/cyberdeck-bt-pair.sh"
  emit_firstboot "$user" "$dir" > "$out/cyberdeck-firstboot.sh"
  emit_firstboot_unit > "$out/cyberdeck-firstboot.service"
  chmod +x "$out/cyberdeck-bt-pair.sh" "$out/cyberdeck-firstboot.sh"
  note "wrote $out:"
  ls -1 "$out" | sed 's/^/     /'
}

# ------------------------------------------------------------------ build --

fetch_image() {
  mkdir -p "$BUILD_DIR"
  local url src
  if [[ -n "${CFG[DECK_IMAGE_PATH]:-}" ]]; then
    src="${CFG[DECK_IMAGE_PATH]}"
    [[ -f "$src" ]] || die "DECK_IMAGE_PATH points at nothing: $src"
    note "using $src"
  else
    [[ "${CFG[DECK_IMAGE_VARIANT]}" == armhf ]] && url="$RPI_IMAGE_ARMHF" || url="$RPI_IMAGE_ARM64"
    src="${BUILD_DIR}/raspios-${CFG[DECK_IMAGE_VARIANT]}.img.xz"
    if [[ ! -f "$src" ]]; then
      step "Downloading Raspberry Pi OS Lite (${CFG[DECK_IMAGE_VARIANT]})"
      curl -L --progress-bar -o "$src" "$url"
    else
      note "already downloaded: $src"
    fi
  fi
  step "Decompressing to $IMAGE_OUT"
  rm -f "$IMAGE_OUT"
  if [[ "$src" == *.xz ]]; then
    xz -dc "$src" > "$IMAGE_OUT"
  else
    cp "$src" "$IMAGE_OUT"
  fi
  note "$(du -h "$IMAGE_OUT" | cut -f1)"
}

LOOP_DEV=""; BOOT_MNT=""; ROOT_MNT=""

cleanup() {
  local had_e=""
  [[ $- == *e* ]] && had_e=yes
  set +e
  [[ -n "$ROOT_MNT" ]] && sudo umount "$ROOT_MNT" 2>/dev/null
  [[ -n "$BOOT_MNT" ]] && sudo umount "$BOOT_MNT" 2>/dev/null
  [[ -n "$LOOP_DEV" ]] && sudo losetup -d "$LOOP_DEV" 2>/dev/null
  [[ -n "$ROOT_MNT" ]] && rmdir "$ROOT_MNT" 2>/dev/null
  [[ -n "$BOOT_MNT" ]] && rmdir "$BOOT_MNT" 2>/dev/null
  LOOP_DEV=""; BOOT_MNT=""; ROOT_MNT=""
  [[ -n "$had_e" ]] && set -e
  return 0
}

mount_image() {
  step "Mounting the image"
  LOOP_DEV="$(sudo losetup --find --show --partscan "$IMAGE_OUT")" || die "losetup failed"
  note "loop device: $LOOP_DEV"

  # losetup returns once the kernel has read the partition table, but udev
  # creates the /dev/loopNpM nodes afterwards. Testing for them immediately is
  # a race; losing it reports a perfectly good image as not a Pi image.
  command -v udevadm >/dev/null && sudo udevadm settle --timeout=10 2>/dev/null
  local i
  for i in $(seq 1 20); do
    [[ -e "${LOOP_DEV}p1" && -e "${LOOP_DEV}p2" ]] && break
    if (( i == 8 )); then
      sudo partx -a "$LOOP_DEV" 2>/dev/null || sudo partprobe "$LOOP_DEV" 2>/dev/null || true
    fi
    sleep 0.25
  done
  [[ -e "${LOOP_DEV}p1" && -e "${LOOP_DEV}p2" ]] \
    || die "expected two partitions on $LOOP_DEV — is this a Raspberry Pi OS image?"

  BOOT_MNT="$(mktemp -d)"; ROOT_MNT="$(mktemp -d)"
  sudo mount "${LOOP_DEV}p1" "$BOOT_MNT" || die "cannot mount the boot partition"
  sudo mount "${LOOP_DEV}p2" "$ROOT_MNT" || die "cannot mount the root partition"
}

expand_tilde() { [[ "${1:-}" == "~"* ]] && echo "${HOME}${1:1}" || echo "${1:-}"; }

configure_access() {
  step "Account, hostname and SSH"
  [[ "${CFG[DECK_SSH]:-yes}" == yes ]] && sudo touch "${BOOT_MNT}/ssh"

  local hash
  hash="$(openssl passwd -6 "${CFG[DECK_USER_PASSWORD]}")" || die "password hashing failed"
  echo "${CFG[DECK_USER]}:${hash}" | sudo tee "${BOOT_MNT}/userconf.txt" >/dev/null
  sudo chmod 600 "${BOOT_MNT}/userconf.txt"

  # Nothing may be written under /home at build time: Raspberry Pi OS processes
  # userconf.txt with "usermod -m -d /home/<name>", which refuses to run if the
  # directory already exists. The key is staged elsewhere and moved on first boot.
  local pubkey; pubkey="$(expand_tilde "${CFG[DECK_SSH_PUBKEY]:-}")"
  if [[ -n "$pubkey" && -f "$pubkey" ]]; then
    sudo mkdir -p "${ROOT_MNT}/etc/cyberdeck"
    sudo cp "$pubkey" "${ROOT_MNT}/etc/cyberdeck/authorized_keys"
    sudo chmod 644 "${ROOT_MNT}/etc/cyberdeck/authorized_keys"
    note "SSH key staged"
  fi

  echo "${CFG[DECK_HOSTNAME]}" | sudo tee "${ROOT_MNT}/etc/hostname" >/dev/null
  sudo sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t${CFG[DECK_HOSTNAME]}/" "${ROOT_MNT}/etc/hosts"
  note "${CFG[DECK_USER]}@${CFG[DECK_HOSTNAME]}.local"
}

configure_wifi() {
  step "WiFi"
  local nm_dir="${ROOT_MNT}/etc/NetworkManager/system-connections"
  sudo mkdir -p "$nm_dir"
  local n=1 ssid psk prio tmp
  while [[ -n "${CFG[DECK_WIFI_SSID_$n]:-}" ]]; do
    ssid="${CFG[DECK_WIFI_SSID_$n]}"; psk="${CFG[DECK_WIFI_PSK_$n]:-}"
    prio=$((100 - n))
    tmp="$(mktemp)"
    cat > "$tmp" <<EOF
[connection]
id=${ssid}
type=wifi
autoconnect=true
autoconnect-priority=${prio}

[wifi]
mode=infrastructure
ssid=${ssid}
cloned-mac-address=permanent

[wifi-security]
key-mgmt=wpa-psk
psk=${psk}

[ipv4]
method=auto

[ipv6]
method=auto
EOF
    # NetworkManager silently ignores a profile that is group- or world-readable,
    # which looks exactly like a wrong password.
    sudo cp "$tmp" "${nm_dir}/${ssid}.nmconnection"
    sudo chmod 600 "${nm_dir}/${ssid}.nmconnection"
    sudo chown 0:0 "${nm_dir}/${ssid}.nmconnection"
    rm -f "$tmp"
    note "network ${n}: ${ssid}"
    n=$((n + 1))
  done

  # Raspberry Pi OS ships the WiFi radio rfkill-blocked and keeps it blocked
  # until a regulatory domain is set. That has to happen before NetworkManager
  # comes up, because first boot needs the network to install packages — and a
  # deck with no network installs no fldigi and no bluez, which presents as
  # "no connection to fldigi" plus a keyboard that never pairs.
  #
  # Set it three ways so no single mechanism's absence on a given OS release
  # leaves the deck offline. This mirrors the iGate build, where the same
  # approach is proven on this board.
  local country="${CFG[DECK_WIFI_COUNTRY]}"

  # 1. Kernel module parameter — applied as the driver loads, before userspace.
  sudo mkdir -p "${ROOT_MNT}/etc/modprobe.d"
  printf 'options cfg80211 ieee80211_regdom=%s\n' "$country" \
    | sudo tee "${ROOT_MNT}/etc/modprobe.d/cfg80211-regdom.conf" >/dev/null

  # 2. Legacy CRDA default, still read on older releases.
  echo "REGDOMAIN=${country}" | sudo tee "${ROOT_MNT}/etc/default/crda" >/dev/null 2>&1 || true
  sudo sed -i 's/^country=.*//' "${BOOT_MNT}/wpa_supplicant.conf" 2>/dev/null || true

  # 3. An early oneshot that unblocks the radios and records the country,
  #    ordered ahead of NetworkManager. Mechanisms 1 and 2 set the domain but
  #    neither clears the soft block; without this the radio stays down.
  tmp="$(mktemp)"
  cat > "$tmp" <<EOF
[Unit]
Description=Unblock the radios and set the WiFi regulatory domain
Before=NetworkManager.service wpa_supplicant.service bluetooth.service
After=local-fs.target
ConditionPathExists=!/var/lib/cyberdeck-wifi-country-done

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/cyberdeck-wifi-country.sh

[Install]
WantedBy=multi-user.target
EOF
  sudo install -m 644 "$tmp" "${ROOT_MNT}/etc/systemd/system/cyberdeck-wifi-country.service"

  cat > "$tmp" <<EOF
#!/usr/bin/env bash
# Unblocks the WiFi and Bluetooth radios and records the regulatory domain.
# Runs once, before NetworkManager, so first boot has a network to install
# over. Bluetooth is unblocked here too: the deck's only keyboard is Bluetooth.
set -uo pipefail
COUNTRY="${country}"

command -v rfkill >/dev/null && rfkill unblock wifi bluetooth
command -v iw >/dev/null && iw reg set "\$COUNTRY"
command -v raspi-config >/dev/null && raspi-config nonint do_wifi_country "\$COUNTRY"

# systemd-rfkill replays a persisted block on boot, which undoes the unblock
# above on the next start unless the stored state is cleared too.
for f in /var/lib/systemd/rfkill/*:wlan /var/lib/systemd/rfkill/*:bluetooth; do
  [[ -e "\$f" ]] && echo 0 > "\$f"
done

mkdir -p /var/lib
touch /var/lib/cyberdeck-wifi-country-done
exit 0
EOF
  sudo install -D -m 755 "$tmp" "${ROOT_MNT}/usr/local/sbin/cyberdeck-wifi-country.sh"
  rm -f "$tmp"

  # configure_wifi runs before the units are installed, so the wants directory
  # is whatever the stock image has. Create it rather than assume it.
  sudo mkdir -p "${ROOT_MNT}/etc/systemd/system/multi-user.target.wants"
  sudo ln -sf /etc/systemd/system/cyberdeck-wifi-country.service \
    "${ROOT_MNT}/etc/systemd/system/multi-user.target.wants/cyberdeck-wifi-country.service"

  note "regulatory domain ${country}, radios unblocked before NetworkManager"
}

install_project() {
  step "Installing the terminal"
  local dest="${ROOT_MNT}/opt/${CFG[DECK_INSTALL_DIR]:-cyberdeck}"
  sudo mkdir -p "$dest"
  sudo rsync -a \
    --exclude '.git/' --exclude '__pycache__/' --exclude 'deck-build/' \
    --exclude 'deck.secrets' --exclude 'docs/' --exclude 'fldigi-config/' \
    "${SCRIPT_DIR}/" "${dest}/"

  # The station's own settings. cyberdeck.conf is gitignored, so fall back to
  # the example rather than shipping a card with no configuration at all.
  if [[ -f "${SCRIPT_DIR}/cyberdeck.conf" ]]; then
    sudo cp "${SCRIPT_DIR}/cyberdeck.conf" "${dest}/cyberdeck.conf"
    note "cyberdeck.conf installed"
  else
    sudo cp "${SCRIPT_DIR}/cyberdeck.conf.example" "${dest}/cyberdeck.conf"
    note "no cyberdeck.conf here; installed the example — set CALLSIGN on the deck"
  fi

  # A seeded fldigi configuration. fldigi crashes on an empty one, with an
  # assertion failure during first-run setup, so the card cannot be left to
  # generate its own.
  local seed=""
  [[ -d "${SCRIPT_DIR}/fldigi-config" ]] && seed="${SCRIPT_DIR}/fldigi-config"
  [[ -z "$seed" && -d "$HOME/.fldigi" ]] && seed="$HOME/.fldigi"
  [[ -n "$seed" ]] || die "no fldigi configuration to seed from. Run ./dev-fldigi.sh once, or run fldigi on a desktop."
  sudo rsync -a --exclude 'fldigi.log' "${seed}/" "${dest}/fldigi-config/"
  note "fldigi config seeded from ${seed}"

  sudo mkdir -p "${dest}/run"
  note "installed to /opt/${CFG[DECK_INSTALL_DIR]:-cyberdeck}"
}

configure_boot() {
  step "Boot settings"
  local cfg="${BOOT_MNT}/config.txt" cmd="${BOOT_MNT}/cmdline.txt"

  if [[ -n "${CFG[DECK_PANEL_OVERLAY]:-}" ]]; then
    # config.txt is divided into conditional sections ([cm4], [pi5], [all]...)
    # and a bare append inherits whichever section happens to be last in the
    # stock file. Today that is [all]; if an image ever ended with [pi5] the
    # overlay would silently not apply to a 3A+. Open [all] explicitly, once,
    # and write everything below it.
    printf '\n[all]\n' | sudo tee -a "$cfg" >/dev/null

    # The panel overlay needs the KMS driver loaded first. Raspberry Pi OS
    # ships vc4-kms-v3d enabled, but a config.txt where it has been commented
    # out gives a blank panel and no other symptom, so assert it rather than
    # assume it. Waveshare's instructions list both lines for this reason.
    if sudo grep -qE '^[[:space:]]*dtoverlay=vc4-kms-v3d' "$cfg"; then
      note "dtoverlay=vc4-kms-v3d already present"
    else
      printf '# Cyberdeck: KMS driver, required by the panel overlay below.\ndtoverlay=vc4-kms-v3d\n' \
        | sudo tee -a "$cfg" >/dev/null
      note "dtoverlay=vc4-kms-v3d added"
    fi

    printf '# Cyberdeck: the DSI panel.\ndtoverlay=%s\n' "${CFG[DECK_PANEL_OVERLAY]}" \
      | sudo tee -a "$cfg" >/dev/null
    note "dtoverlay=${CFG[DECK_PANEL_OVERLAY]} (under [all])"
  fi

  if [[ "${CFG[DECK_HIDE_BOOT_MESSAGES]:-yes}" == yes && -f "$cmd" ]]; then
    # A blank screen until the terminal appears, rather than a wall of kernel
    # messages followed by a login prompt nobody will ever type into.
    local line; line="$(sudo cat "$cmd")"
    line="${line//console=tty1/console=tty3}"
    for opt in quiet loglevel=0 logo.nologo vt.global_cursor_default=0; do
      [[ "$line" == *"$opt"* ]] || line="${line} ${opt}"
    done
    echo "$line" | sudo tee "$cmd" >/dev/null
    note "quiet boot, no cursor, kernel messages moved to tty3"
  fi
}

harden_card() {
  step "Reducing writes to the card"
  local dir="/opt/${CFG[DECK_INSTALL_DIR]:-cyberdeck}"
  local size="${CFG[DECK_RUN_TMPFS_SIZE]:-32M}"
  if ! sudo grep -q "${dir}/run" "${ROOT_MNT}/etc/fstab" 2>/dev/null; then
    printf 'tmpfs %s/run tmpfs defaults,noatime,nosuid,nodev,size=%s,mode=0755 0 0\n' \
      "$dir" "$size" | sudo tee -a "${ROOT_MNT}/etc/fstab" >/dev/null
    note "run/ on a ${size} tmpfs"
  fi
  sudo mkdir -p "${ROOT_MNT}/etc/systemd/journald.conf.d"
  printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=16M\n' \
    | sudo tee "${ROOT_MNT}/etc/systemd/journald.conf.d/volatile.conf" >/dev/null
  note "journal in RAM"
}

install_services() {
  step "systemd units"
  local user="${CFG[DECK_USER]}" dir="/opt/${CFG[DECK_INSTALL_DIR]:-cyberdeck}"
  local sysd="${ROOT_MNT}/etc/systemd/system"
  local wants="${sysd}/multi-user.target.wants"
  sudo mkdir -p "$sysd" "$wants" "${sysd}/timers.target.wants"

  local u tmp; tmp="$(mktemp)"
  # install -m, not cp: the temp file is mktemp's 0600, and a plain cp carries
  # that mode onto the unit. systemd reads it either way, but unit files with
  # mixed permissions invite a later "why is this one different".
  for u in xvfb fldigi rigctld ui btpair; do
    emit_unit "$u" "$user" "$dir" > "$tmp"
    sudo install -m 644 "$tmp" "${sysd}/cyberdeck-${u}.service"
  done
  emit_unit btpair-timer "$user" "$dir" > "$tmp"
  sudo install -m 644 "$tmp" "${sysd}/cyberdeck-btpair.timer"
  emit_bt_script > "$tmp"
  sudo install -D -m 755 "$tmp" "${ROOT_MNT}/usr/local/sbin/cyberdeck-bt-pair.sh"
  rm -f "$tmp"

  # Enabled by symlink: systemctl enable cannot run against an offline image.
  local s
  for s in cyberdeck-xvfb cyberdeck-fldigi cyberdeck-rigctld cyberdeck-btpair; do
    sudo ln -sf "/etc/systemd/system/${s}.service" "${wants}/${s}.service"
  done
  sudo ln -sf /etc/systemd/system/cyberdeck-btpair.timer \
    "${sysd}/timers.target.wants/cyberdeck-btpair.timer"
  if [[ "${CFG[DECK_AUTOSTART]:-yes}" == yes ]]; then
    sudo ln -sf /etc/systemd/system/cyberdeck-ui.service "${wants}/cyberdeck-ui.service"
    # The terminal owns tty1, so the login prompt must not also claim it.
    sudo ln -sf /dev/null "${sysd}/getty@tty1.service"
    note "terminal starts on tty1 at boot; getty on tty1 masked"
  else
    note "terminal installed but not enabled (DECK_AUTOSTART is not yes)"
  fi
  install_firstboot "$user" "$dir"
}

emit_firstboot() {  # user dir
  local user="$1" dir="$2"
  cat <<EOF
#!/usr/bin/env bash
# Runs once: installs what the terminal needs and moves the SSH key into place.
set -uo pipefail
echo "Cyberdeck first-boot setup..."
export DEBIAN_FRONTEND=noninteractive

for i in \$(seq 1 30); do
  getent hosts deb.debian.org >/dev/null 2>&1 && break
  echo "  waiting for DNS (\$i/30)..."; sleep 10
done

apt-get update -y || exit 1
apt-get install -y --no-install-recommends \\
  fldigi xvfb libhamlib-utils python3 console-setup fonts-terminus \\
  kbd bluez alsa-utils || exit 1

HOME_DIR="\$(getent passwd ${user} | cut -d: -f6)"
if [[ -f /etc/cyberdeck/authorized_keys && -n "\$HOME_DIR" ]]; then
  mkdir -p "\$HOME_DIR/.ssh"
  cp /etc/cyberdeck/authorized_keys "\$HOME_DIR/.ssh/authorized_keys"
  chmod 700 "\$HOME_DIR/.ssh"; chmod 600 "\$HOME_DIR/.ssh/authorized_keys"
  chown -R ${user}:${user} "\$HOME_DIR/.ssh"
fi
[[ -n "\$HOME_DIR" && ! -e "\$HOME_DIR/$(basename "$dir")" ]] && \\
  ln -s "$dir" "\$HOME_DIR/$(basename "$dir")" && \\
  chown -h ${user}:${user} "\$HOME_DIR/$(basename "$dir")"

chown -R ${user}:${user} "$dir"
touch /var/lib/cyberdeck-firstboot-done
systemctl start cyberdeck-xvfb cyberdeck-fldigi cyberdeck-ui 2>/dev/null || true
echo "Setup complete."
EOF
}

emit_firstboot_unit() {
  cat <<'EOF'
[Unit]
Description=First-boot setup for the cyberdeck
After=network-online.target userconf.service
Wants=network-online.target
ConditionPathExists=!/var/lib/cyberdeck-firstboot-done

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/cyberdeck-firstboot.sh
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
EOF
}

install_firstboot() {
  local user="$1" dir="$2" tmp; tmp="$(mktemp)"
  emit_firstboot "$user" "$dir" > "$tmp"
  sudo install -D -m 755 "$tmp" "${ROOT_MNT}/usr/local/sbin/cyberdeck-firstboot.sh"
  emit_firstboot_unit > "$tmp"
  sudo install -m 644 "$tmp" "${ROOT_MNT}/etc/systemd/system/cyberdeck-firstboot.service"
  sudo ln -sf /etc/systemd/system/cyberdeck-firstboot.service \
    "${ROOT_MNT}/etc/systemd/system/multi-user.target.wants/cyberdeck-firstboot.service"
  rm -f "$tmp"
  note "first-boot installer staged"
}

cmd_build() {
  validate
  require_tools
  fetch_image
  trap cleanup EXIT INT TERM
  mount_image
  configure_access
  configure_wifi
  install_project
  configure_boot
  harden_card
  install_services
  sync
  cleanup
  trap - EXIT INT TERM
  step "Done"
  note "$IMAGE_OUT"
  note "flash it with: $0 flash /dev/sdX   (check lsblk first)"
}

cmd_flash() {
  local dev="${1:-}"
  [[ -n "$dev" ]] || die "usage: $0 flash /dev/sdX   (check lsblk first)"
  [[ -b "$dev" ]] || die "$dev is not a block device"
  [[ -f "$IMAGE_OUT" ]] || die "no image at $IMAGE_OUT; run '$0 build' first"
  # Refusing a whole-disk device that is mounted is the difference between
  # flashing a card and flashing a laptop.
  if lsblk -no MOUNTPOINT "$dev" 2>/dev/null | grep -q .; then
    die "$dev has mounted partitions; unmount them first"
  fi
  echo
  echo "About to OVERWRITE $dev with $IMAGE_OUT:"
  lsblk -o NAME,SIZE,TYPE,MOUNTPOINT "$dev" || true
  echo
  read -r -p "Type the device path again to confirm: " confirm
  [[ "$confirm" == "$dev" ]] || die "not confirmed"
  step "Writing"
  sudo dd if="$IMAGE_OUT" of="$dev" bs=4M status=progress conv=fsync
  sync
  note "done; eject before removing the card"
}

main() {
  case "${1:-check}" in
    check) validate ;;
    units) cmd_units "${2:-}" ;;
    build) cmd_build ;;
    flash) cmd_flash "${2:-}" ;;
    *)
      echo "Usage: $0 {check|units [dir]|build|flash /dev/sdX}" >&2
      exit 1 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then main "$@"; fi
