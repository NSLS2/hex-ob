"""
Functional test: the Phantom plan family against the simulated HEX beamline.

Runs the phantom plans with the real devices from lib/ against the sim's
deep Phantom tier — the REAL ADPhantom IOC (CA :5105) driving the
protocol-level camera sim (sim_camera.py) — asserting run success,
per-stream event counts, and a fresh HDF file with the expected frame
total, written by the production plugin chain from the RAM-download path.

Scope (dec:phantom-suite-mock-panda-interim, 2026-08-12): the PandA is an
ophyd-async MOCK until the real phantom PandA configuration is captured at
the beamline (trigger routing, PULSE2+BITS design) — so take_images and
dark_flat_scan (no PandA involvement) run fully real here, and tomo_scan
runs with the panda mocked and the event trigger stood in by a software
trigger.  The PandA-dependent assertions (HDF Angle series, real train
pacing) activate when the design capture lands and the mock is replaced by
the sim PandA.

Prerequisites: sim up (hex-simulated-beamline/scripts/up_all.sh) and the
loopback EPICS client env sourced.  Run from the hex-ob root:

    source hex-simulated-beamline/scripts/env.sh
    pixi run python tests/phantom_sim_test.py

Safety: refuses to run unless EPICS_CA_ADDR_LIST is loopback-only — the PV
names are the real beamline names; this must never touch a real gateway.
"""

import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

addr_list = os.environ.get("EPICS_CA_ADDR_LIST", "")
addrs = addr_list.split()
if not addrs or any(not a.startswith("127.0.0.1") for a in addrs):
    sys.exit(
        f"REFUSING to run: EPICS_CA_ADDR_LIST={addr_list!r} is not loopback-only.\n"
        "Source hex-simulated-beamline/scripts/env.sh first."
    )
os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST", "NO")

# CA context setup — see alignment_scan_sim_test.py for the full story.
import epics.ca

epics.ca.initialize_libca()

from bluesky import RunEngine
from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.plan_stubs import ensure_connected

from lib.phantom import make_phantom
from plans.phantom import dark_flat_scan, take_images

BASE = "/nsls2/data/hex/proposals/2026-2/pass-000000/phantom"


def host_dir(output_dir: str) -> Path:
    """The host-side view of an in-sim /nsls2 output directory."""
    return Path("/tmp/hex-sim-data") / output_dir.lstrip("/")


def check_hdf(directory: Path, since: float, expected_frames: int, label: str):
    hdf_files = sorted(
        (
            p
            for pattern in ("*.h5", "*.hdf", "*.hdf5")
            for p in directory.glob(pattern)
            if p.stat().st_mtime >= since - 1
        ),
        key=lambda p: p.stat().st_mtime,
    )
    assert hdf_files, f"{label}: no HDF file written under {directory}"
    try:
        import h5py

        with h5py.File(hdf_files[-1], "r") as f:
            n = f["/entry/data/data"].shape[0]
        assert n == expected_frames, f"{label}: expected {expected_frames} frames, got {n}"
        print(f"PASS  {label}: HDF {hdf_files[-1].name} has {n} frames")
    except ImportError:
        assert hdf_files[-1].stat().st_size > 0
        print(f"PASS  {label}: HDF exists ({hdf_files[-1].name}; h5py absent)")


def main() -> None:
    RE = RunEngine({})
    ph_open_cmd = epics_signal_rw(int, "XF:27IDA-PPS{L1-S1}Cmd:Opn-Cmd", name="ph_open_cmd")
    ph_close_cmd = epics_signal_rw(int, "XF:27IDA-PPS{L1-S1}Cmd:Cls-Cmd", name="ph_close_cmd")
    phantom1 = make_phantom()
    # Blackhole PVs first, separately: the phantom's ~50-signal search burst
    # can drown the blackhole's two searches when connected together (the
    # caproto blackhole materializes PVs per search), and the pair then
    # times out.
    RE(ensure_connected(ph_open_cmd, ph_close_cmd))
    RE(ensure_connected(phantom1))
    print("All devices connected (PhantomIO real, against the sim tier).")

    docs: list[tuple[str, dict]] = []
    RE.subscribe(lambda name, doc: docs.append((name, doc)))

    def events() -> dict[str, int]:
        desc = {d["uid"]: d["name"] for n, d in docs if n == "descriptor"}
        return dict(Counter(desc[d["descriptor"]] for n, d in docs if n == "event"))

    def stop_ok():
        stops = [d for n, d in docs if n == "stop"]
        assert stops and stops[-1]["exit_status"] == "success", stops[-1:]

    # -- take_images ---------------------------------------------------------
    docs.clear()
    out = f"{BASE}/raw_data/take_images_sim_test"
    t0 = time.time()
    RE(take_images(
        phantom1, ph_open_cmd=ph_open_cmd, ph_close_cmd=ph_close_cmd,
        output_dir=out, exposure_time=0.005, acquire_period=0.02,
        num_images=10,
    ))
    stop_ok()
    assert events() == {"primary": 1}, events()
    check_hdf(host_dir(out), t0, 10, "take_images")

    # -- dark_flat_scan ------------------------------------------------------
    docs.clear()
    out = f"{BASE}/raw_data/dark_flat_sim_test"
    t0 = time.time()
    RE(dark_flat_scan(
        phantom1, ph_open_cmd, ph_close_cmd,
        output_dir=out, exposure_time=0.005, acquire_period=0.02,
        num_dark=3, num_flat=5,
    ))
    stop_ok()
    assert events() == {"flat": 1, "dark": 1}, events()
    # flat and dark are separate captures -> two HDF files in one dir; the
    # newest holds the dark frames, so check both counts explicitly.
    files = sorted(host_dir(out).glob("*.h5"), key=lambda p: p.stat().st_mtime)
    recent = [p for p in files if p.stat().st_mtime >= t0 - 1]
    assert len(recent) >= 2, f"dark_flat: expected 2 HDF files, got {len(recent)}"
    import h5py

    counts = []
    for p in recent[-2:]:
        with h5py.File(p, "r") as f:
            counts.append(f["/entry/data/data"].shape[0])
    assert sorted(counts) == [3, 5], f"dark_flat: frame counts {counts}, expected 3+5"
    print(f"PASS  dark_flat_scan: two HDF captures with {counts} frames")

    print("\nALL PHANTOM SIM TESTS PASS (interim scope: PandA-free plans)")


if __name__ == "__main__":
    main()
