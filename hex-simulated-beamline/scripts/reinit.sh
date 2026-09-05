#!/usr/bin/env bash
# Re-apply the IOC-level settings that live only in memory (step 4 of up_all.sh).
# Run after ANY container restart of panda-sim / panda-ioc / kinetix-ioc — a plain
# `docker stop/start` loses them: the Kinetix personality (TriggerMode choices,
# ArrayCallbacks) reverts to ADSimDetector's defaults and the PandA design is gone.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
PY="${PY:-$root/.toolenv/bin/python}"
[ -x "$PY" ] || PY=python3
"$PY" "$root/iocs/panda/hex_tomo_design.py"
EPICS_CA_ADDR_LIST=127.0.0.1:5095 "$PY" "$root/iocs/panda/init_panda_ioc.py"
EPICS_CA_ADDR_LIST=127.0.0.1:5085 "$PY" "$root/iocs/kinetix/init_kinetix.py"
echo "[reinit] done."
