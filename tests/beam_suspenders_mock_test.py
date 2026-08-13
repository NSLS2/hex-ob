"""
Mock tests for the beam-availability suspenders (lib/beam.py).

Soft signals stand in for the ring-current and front-end-permit PVs; the
test drives them and asserts the stock bluesky suspenders — watching
ophyd-async signals through the compatibility shim — trip, hold through
the resume hysteresis, and release, replacing the legacy scripts'
in-scan permit-wait loops.

Run from the hex-ob root:  python tests/beam_suspenders_mock_test.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bluesky.run_engine import RunEngine
from ophyd_async.core import soft_signal_rw

from lib.beam import install_beam_suspenders


def main() -> None:
    ring = soft_signal_rw(float, initial_value=400.0, name="ring_current")
    permit = soft_signal_rw(int, initial_value=1, name="fe_permit")
    asyncio.run(ring.connect())
    asyncio.run(permit.connect())

    RE = RunEngine({})
    susp_current, susp_permit = install_beam_suspenders(
        RE, ring, permit, sleep=0.01
    )

    def put(signal, value, settle: float = 0.5):
        """Set from the RE's loop (signal.set must be CALLED in-loop) and
        give the monitor callback time to land."""
        async def _do():
            await signal.set(value)

        asyncio.run_coroutine_threadsafe(_do(), RE.loop).result()
        deadline = time.monotonic() + settle
        time.sleep(0.05)
        return deadline

    def wait_tripped(susp, expected: bool, deadline: float, what: str):
        while time.monotonic() < deadline:
            if susp.tripped == expected:
                return
            time.sleep(0.02)
        raise AssertionError(f"{what}: tripped != {expected}")

    assert len(RE.suspenders) == 2
    assert not susp_current.tripped and not susp_permit.tripped
    print("PASS  install (2 suspenders, untripped at nominal values)")

    wait_tripped(susp_current, True, put(ring, 50.0), "ring 50 mA")
    print("PASS  ring current below 100 mA trips")

    # hysteresis: above the 100 suspend floor but below the 390 resume
    put(ring, 200.0)
    time.sleep(0.3)
    assert susp_current.tripped, "200 mA must NOT resume (resume_thresh=390)"
    print("PASS  resume hysteresis holds below 390 mA")

    wait_tripped(susp_current, False, put(ring, 400.0), "ring 400 mA")
    print("PASS  ring current above 390 mA releases")

    wait_tripped(susp_permit, True, put(permit, 0), "permit 0")
    wait_tripped(susp_permit, False, put(permit, 1), "permit 1")
    print("PASS  front-end permit trips low, releases high")

    susp_current.remove()
    susp_permit.remove()
    # after removal the signals no longer reach the suspenders
    put(ring, 10.0)
    time.sleep(0.3)
    assert not susp_current.tripped, "removed suspender must not trip"
    print("PASS  remove() detaches the subscription")

    print("\nALL PASS")


if __name__ == "__main__":
    main()
