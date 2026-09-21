#!/usr/bin/env bash
# Run every test and summarize. Each file is a standalone script that prints
# its own checks and ends with ALL PASS, so this reports per file rather than
# collecting assertions.
#
# fldigi must be running: four of these drive the real application through a
# pseudo-terminal and read the screen back, which needs a modem to talk to.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${HERE}/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

if ! python3 -c "
import xmlrpc.client, sys
try:
    xmlrpc.client.ServerProxy('http://127.0.0.1:7362/').fldigi.name_version()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
  echo "fldigi is not answering on 127.0.0.1:7362 — start it with tools/dev-fldigi.sh" >&2
  exit 1
fi

failed=0
total=0
for t in tests/test_*.py; do
  out="$(python3 "$t" 2>&1)"
  checks=$(grep -c 'PASS' <<<"$out")
  if grep -q 'ALL PASS' <<<"$out"; then
    printf '  %-28s ALL PASS (%d)\n' "$t" "$((checks - 1))"
    total=$((total + checks - 1))
  else
    printf '  %-28s FAILED\n' "$t"
    grep -iE '^  FAIL' <<<"$out" | sed 's/^/      /'
    failed=$((failed + 1))
  fi
done

echo
if (( failed )); then
  echo "${failed} file(s) failed"
  exit 1
fi
echo "${total} checks, all passing"
