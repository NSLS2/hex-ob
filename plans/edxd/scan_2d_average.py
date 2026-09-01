"""
1-D EDXD step scan with a spatial-averaging sweep on a second motor.

Equivalent of the old pyepics script:
    hex-acq-pyepics/techniques/edxd/scan_2d_average.py

Steps *motor1* through its range; at each point *motor2* sweeps from
*start2* to *stop2* ACROSS the exposure — its velocity is set to
span / count_time so the sweep and the count finish together, spatially
averaging the spectrum over the sweep axis.  Between points motor2 rewinds
to *start2* at *travel_velocity* (the original hardcoded 0.5).

One exposure per motor1 position into ``primary`` (motor1 readback per
point; motor2 is mid-flight during the exposure, so it is not read into
the event — its range and velocity are in the run metadata).
``num_iterations`` repeats the scan as separate runs.  Both motors and
motor2's velocity are restored at the very end.

The sweep velocity is NOT validated against the motor record's VMAX — a
too-short count_time over a long span will ask for a speed the motor
cannot do.  Confirm sensible combinations at the beamline.
"""

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
from ophyd_async.core import TriggerInfo

from lib.shutter import close_photon_shutter, open_photon_shutter

from .scan_edxd import _check_shutter_args, _positions

_SWEEP_GROUP = "edxd_average_sweep"


def scan_2d_average(
    detector,
    motor1,
    motor2,
    *,
    start1: float,
    stop1: float,
    num_points1: int,
    start2: float,
    stop2: float,
    count_time: float,
    travel_velocity: float = 0.5,
    num_iterations: int = 1,
    sleep_time: float = 0.0,
    deadtime: float = 0.002,
    ph_open_cmd=None,
    ph_close_cmd=None,
    md: dict | None = None,
):
    """
    Step *motor1*; at each point sweep *motor2* across the exposure.

    Parameters
    ----------
    detector : preparable/triggerable ophyd-async detector
    motor1 : Movable
        The stepped scan motor.
    motor2 : Motor
        The averaging sweep motor (its ``velocity`` signal is driven).
    start1 / stop1 / num_points1 : float, float, int
        Step range and point count.
    start2 / stop2 : float
        Sweep range; must differ (the sweep velocity is span/count_time).
    count_time : float
        Exposure time per point, seconds.
    travel_velocity : float, optional
        motor2 velocity for the rewind between points and the final
        restore. Default 0.5 (the original's hardcoded value).
    num_iterations / sleep_time / deadtime / ph_open_cmd / ph_close_cmd / md :
        As in ``scan_edxd_2d``.
    """
    _check_shutter_args(ph_open_cmd, ph_close_cmd)
    positions = _positions(start1, stop1, num_points1)
    if start2 == stop2:
        raise ValueError("start2 and stop2 must differ (sweep range).")
    if count_time <= 0:
        raise ValueError(f"count_time must be > 0, got {count_time}")
    if travel_velocity <= 0:
        raise ValueError(f"travel_velocity must be > 0, got {travel_velocity}")
    if num_iterations < 1:
        raise ValueError(f"num_iterations must be >= 1, got {num_iterations}")

    sweep_velocity = abs(stop2 - start2) / count_time

    _md = {
        "plan_name": "scan_2d_average",
        "detectors": [detector.name],
        "motors": [motor1.name],
        "sweep_motor": motor2.name,
        "count_time": count_time,
        "sweep_start": start2,
        "sweep_stop": stop2,
        "sweep_velocity": sweep_velocity,
        "hints": {"dimensions": [([motor1.name], "primary")]},
    }
    _md.update(md or {})

    @bpp.stage_decorator([detector])
    @bpp.run_decorator(md=_md)
    def _scan():
        yield from bps.prepare(
            detector,
            TriggerInfo(livetime=count_time, deadtime=deadtime),
            wait=True,
        )
        print(f"  Averaging sweep velocity for {motor2.name}: "
              f"{sweep_velocity:g} /s over {count_time:g} s")
        for position in positions:
            yield from bps.abs_set(motor2.velocity, travel_velocity, wait=True)
            yield from bps.mv(motor1, float(position), motor2, start2)
            yield from bps.abs_set(motor2.velocity, sweep_velocity, wait=True)
            yield from bps.abs_set(motor2, stop2, group=_SWEEP_GROUP)
            yield from bps.trigger_and_read([detector, motor1])
            yield from bps.wait(group=_SWEEP_GROUP)

    initial1 = yield from bps.rd(motor1)
    initial2 = yield from bps.rd(motor2)

    def _body():
        if ph_open_cmd is not None:
            yield from open_photon_shutter(ph_open_cmd)
        for iteration in range(num_iterations):
            print(f"  EDXD averaging scan iteration {iteration + 1}/{num_iterations}")
            yield from _scan()
            if sleep_time > 0 and iteration < num_iterations - 1:
                yield from bps.sleep(sleep_time)

    def _cleanup():
        yield from bps.abs_set(motor2.velocity, travel_velocity, wait=True)
        print(f"  Returning {motor1.name} to {initial1:g}, "
              f"{motor2.name} to {initial2:g}")
        yield from bps.mv(motor1, initial1, motor2, initial2)
        if ph_close_cmd is not None:
            yield from close_photon_shutter(ph_close_cmd)

    return (yield from bpp.finalize_wrapper(_body(), _cleanup()))
