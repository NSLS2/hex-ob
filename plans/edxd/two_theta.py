"""
2-theta geometry moves.

Equivalent of the old pyepics script:
    hex-acq-pyepics/techniques/edxd/edxd_2theta_tilt.py

The coordinated math lives in the device (lib/edxd_geometry.py); these
plans are the thin operator-facing verbs.  No detector is involved.
"""

import bluesky.plan_stubs as bps


def move_two_theta(geometry, angle_deg: float):
    """
    Realize *angle_deg* 2-theta: coordinated arm + collimator move.

    ``geometry`` is an ``EDXDGeometry``; equivalent of the original's
    ``edxd_2theta_tilt.py -t <angle>``.
    """
    print(f"  Moving EDXD geometry to 2-theta = {angle_deg:g} deg")
    yield from bps.mv(geometry, angle_deg)


def edxd_move_out(geometry):
    """
    Move the EDXD arm out of the beam (X only, to the configured out
    position) — the original's ``-o 1`` mode.
    """
    x_out = yield from bps.rd(geometry.det_x_out)
    print(f"  Moving EDXD arm out of beam: {geometry.det_x.name} -> {x_out:g}")
    yield from bps.mv(geometry.det_x, x_out)
