"""
2-D EDXD raster-scan plan.

Equivalent of the old pyepics script:
    hex-acq-pyepics/techniques/edxd/scan_edxd_2d.py

Rasters *motor2* (outer, rows) over *motor1* (inner, columns): for each
outer position the inner motor rewinds and re-scans — no snaking, matching
the original.  One exposure per grid point into ``primary``, row-major.
``num_iterations`` repeats the whole grid as separate runs (the original's
``-n``, one scan folder per iteration).  Both motors are restored to their
pre-scan positions at the very end, like the original.

Fixes a bug in the original: when the outer range was degenerate
(start2 == stop2) the script built the outer position list with the INNER
point count (``num_point`` instead of ``num_point2``, line 130), silently
changing the number of rows.  Here the outer list always has
``num_points2`` entries.
"""

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
from ophyd_async.core import TriggerInfo

from lib.shutter import close_photon_shutter, open_photon_shutter

from .scan_edxd import _check_shutter_args, _positions


def scan_edxd_2d(
    detector,
    motor1,
    motor2,
    *,
    start1: float,
    stop1: float,
    num_points1: int,
    start2: float,
    stop2: float,
    num_points2: int,
    count_time: float,
    num_iterations: int = 1,
    sleep_time: float = 0.0,
    deadtime: float = 0.002,
    ph_open_cmd=None,
    ph_close_cmd=None,
    md: dict | None = None,
):
    """
    Raster: for each *motor2* position, step *motor1* through its range.

    Parameters
    ----------
    detector : preparable/triggerable ophyd-async detector
    motor1 / motor2 : Movable
        Inner (fast) and outer (slow) scan motors.
    start1 / stop1 / num_points1 : float, float, int
        Inner range and point count (columns).
    start2 / stop2 / num_points2 : float, float, int
        Outer range and point count (rows).
    count_time : float
        Exposure time per grid point, seconds.
    num_iterations : int, optional
        Repeat the whole grid this many times, one run each. Default 1.
    sleep_time : float, optional
        Pause between iterations, seconds. Default 0.
    deadtime / ph_open_cmd / ph_close_cmd / md :
        As in ``scan_edxd``.
    """
    _check_shutter_args(ph_open_cmd, ph_close_cmd)
    inner = _positions(start1, stop1, num_points1)
    outer = _positions(start2, stop2, num_points2)
    if count_time <= 0:
        raise ValueError(f"count_time must be > 0, got {count_time}")
    if num_iterations < 1:
        raise ValueError(f"num_iterations must be >= 1, got {num_iterations}")

    _md = {
        "plan_name": "scan_edxd_2d",
        "detectors": [detector.name],
        "motors": [motor2.name, motor1.name],
        "count_time": count_time,
        "shape": [num_points2, num_points1],
        "hints": {
            "dimensions": [
                ([motor2.name], "primary"),
                ([motor1.name], "primary"),
            ]
        },
    }
    _md.update(md or {})

    @bpp.stage_decorator([detector])
    @bpp.run_decorator(md=_md)
    def _grid():
        yield from bps.prepare(
            detector,
            TriggerInfo(livetime=count_time, deadtime=deadtime),
            wait=True,
        )
        for row in outer:
            yield from bps.mv(motor2, float(row))
            print(f"  Row: {motor2.name} = {row:g}")
            for col in inner:
                yield from bps.mv(motor1, float(col))
                yield from bps.trigger_and_read([detector, motor1, motor2])

    initial1 = yield from bps.rd(motor1)
    initial2 = yield from bps.rd(motor2)

    def _body():
        if ph_open_cmd is not None:
            yield from open_photon_shutter(ph_open_cmd)
        for iteration in range(num_iterations):
            print(f"  EDXD 2-D raster iteration {iteration + 1}/{num_iterations}")
            yield from _grid()
            if sleep_time > 0 and iteration < num_iterations - 1:
                yield from bps.sleep(sleep_time)

    def _cleanup():
        print(f"  Returning {motor1.name} to {initial1:g}, "
              f"{motor2.name} to {initial2:g}")
        yield from bps.mv(motor1, initial1, motor2, initial2)
        if ph_close_cmd is not None:
            yield from close_photon_shutter(ph_close_cmd)

    return (yield from bpp.finalize_wrapper(_body(), _cleanup()))
