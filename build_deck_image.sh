#!/usr/bin/env bash
# Build and flash the cyberdeck's SD card.
#
#   ./build_deck_image.sh check           validate deck.conf and deck.secrets
#   ./build_deck_image.sh units [dir]     write the systemd units out for review
#   ./build_deck_image.sh build           produce deck-build/cyberdeck.img
#   ./build_deck_image.sh flash /dev/sdX  write that image to a card
#
# The card is customised offline on this machine, not on the Pi: the image is
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
  chmod +x "$out/cyberdeck-bt-pair.sh"
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

cmd_build() {
  validate
  require_tools
  fetch_image
  step "Customising the image"
  note "NOT YET IMPLEMENTED: loop-mount and write."
  note "The steps are listed in README.md under 'What the build does'."
  die "build is incomplete; use 'check' and 'units' meanwhile"
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
