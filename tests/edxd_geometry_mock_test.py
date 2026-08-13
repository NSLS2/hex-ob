"""
Mock tests for the EDXD 2-theta geometry device (lib/edxd_geometry.py).

Golden values below were computed by running the LEGACY script's formulas
(hex-acq-pyepics/techniques/edxd/edxd_2theta_tilt.py, with math.degrees in
place of its 57.29578 rounding — difference < 2e-7 deg) for each
(two_theta, z) pair, independently of the device code under test.

Run from the hex-ob root:  python tests/edxd_geometry_mock_test.py
"""

import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bluesky.plan_stubs as bps
from bluesky.run_engine import RunEngine
from ophyd_async.core import init_devices

try:
    from ophyd_async.testing import callback_on_mock_put, set_mock_value
except ImportError:
    from ophyd_async.core._mock_signal_utils import (
        callback_on_mock_put,
        set_mock_value,
    )

from lib.edxd_geometry import EDXDGeometry
from plans.edxd import edxd_move_out, move_two_theta

# (two_theta, z, det_y, coll_pitch, coll_y_coarse) — oracle formulas, defaults
# d1=425, ds=263, r=70.5, slit_offset=24.
GOLDEN = [
    (10.0, 350.0, -61.71444324796274, -5.42216131873867, -29.63497460730195),
    (5.0, 400.0, -34.995465410369604, -4.936389943428329, -8.277891987404573),
    (15.0, 300.0, -80.38475772933681, -17.96940390346213, -10.779884848225597),
]


def make_geometry() -> EDXDGeometry:
    with init_devices(mock=True):
        edxd_geometry = EDXDGeometry()
    motors = (
        edxd_geometry.det_x,
        edxd_geometry.det_y,
        edxd_geometry.det_z,
        edxd_geometry.det_rx,
        edxd_geometry.coll_x,
        edxd_geometry.coll_y_coarse,
        edxd_geometry.coll_pitch,
    )
    for motor in motors:
        callback_on_mock_put(
            motor.user_setpoint,
            lambda value, *, m=motor, **kw: set_mock_value(m.user_readback, value),
        )
    return edxd_geometry


def rb(signal) -> float:
    return asyncio.run(signal.get_value())


def main() -> None:
    RE = RunEngine({})
    geom = make_geometry()

    # -- forward transform against the legacy formulas ----------------------
    for two_theta, z, exp_y, exp_pitch, exp_yc in GOLDEN:
        set_mock_value(geom.det_z.user_readback, z)
        RE(move_two_theta(geom, two_theta))
        assert rb(geom.det_x.user_readback) == 0.0
        assert rb(geom.det_rx.user_readback) == two_theta
        assert rb(geom.coll_x.user_readback) == -54.0
        for signal, expected, label in [
            (geom.det_y.user_readback, exp_y, "det_y"),
            (geom.coll_pitch.user_readback, exp_pitch, "coll_pitch"),
            (geom.coll_y_coarse.user_readback, exp_yc, "coll_y_coarse"),
        ]:
            got = rb(signal)
            assert math.isclose(got, expected, abs_tol=1e-9), (
                f"{label} at 2theta={two_theta}, z={z}: {got} != {expected}"
            )
    print("PASS  forward transform matches legacy formulas (3 golden cases)")

    # -- slit_offset=0 collapses the collimator correction -------------------
    # Independent prediction, no formula duplication: with delta == 0 the
    # collimator pitch equals two_theta exactly.
    set_mock_value(geom.det_z.user_readback, 350.0)
    RE(bps.abs_set(geom.slit_offset, 0.0, wait=True))
    RE(move_two_theta(geom, 10.0))
    assert rb(geom.coll_pitch.user_readback) == 10.0
    RE(bps.abs_set(geom.slit_offset, 24.0, wait=True))
    print("PASS  config signals steer the transform (slit_offset=0 -> pitch==2theta)")

    # -- z <= ds is refused --------------------------------------------------
    set_mock_value(geom.det_z.user_readback, 200.0)
    try:
        RE(move_two_theta(geom, 10.0))
    except Exception as exc:
        assert "must be greater than ds" in repr(exc), exc
    else:
        raise AssertionError("z <= ds should refuse the move")
    print("PASS  z <= ds refused (correction angle undefined)")

    # -- move out is X-only --------------------------------------------------
    set_mock_value(geom.det_z.user_readback, 350.0)
    RE(move_two_theta(geom, 10.0))
    y_before = rb(geom.det_y.user_readback)
    RE(edxd_move_out(geom))
    assert rb(geom.det_x.user_readback) == -270.0
    assert rb(geom.det_y.user_readback) == y_before, "move_out must not touch Y"
    print("PASS  edxd_move_out (X to -270, nothing else moves)")

    print("\nALL PASS")


if __name__ == "__main__":
    main()
