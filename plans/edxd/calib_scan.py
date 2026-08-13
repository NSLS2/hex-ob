"""
EDXD calibration scan: one long exposure while a motor ping-pongs.

Equivalent of the old pyepics script:
    hex-acq-pyepics/techniques/edxd/calib_scan.py

Starts a single *count_time* exposure, then bounces *motor* between
*start* and *stop* for the duration so the calibrant (e.g. Cr2O3 powder)
is averaged over the travel.  When the exposure time has elapsed the
ping-pong stops, the exposure is awaited, and one event is recorded into
``primary``.  The motor is restored to its pre-scan position.

Each ping-pong leg is a completed move: the plan checks the elapsed time
between legs, so the motion can overrun the end of the exposure by at most
one leg (the original polled every 0.5 s and issued a motor stop instead).
Choose the range so a leg is short compared to *count_time*.
"""

import time

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
from ophyd_async.core import TriggerInfo

from lib.shutter import close_photon_shutter, open_photon_shutter

from .scan_edxd import _check_shutter_args

_EXPOSURE_GROUP = "edxd_calib_exposure"


def calib_scan(
    detector,
    motor,
    *,
    start: float,
    stop: float,
    count_time: float,
    deadtime: float = 0.002,
    ph_open_cmd=None,
    ph_close_cmd=None,
    md: dict | None = None,
):
    """
    One *count_time* exposure while *motor* ping-pongs start <-> stop.

    Parameters
    ----------
    detector : preparable/triggerable ophyd-async detector
    motor : Movable
        The motor to sweep (the original defaulted to sample tower Z1).
    start / stop : float
        Ping-pong limits; must differ.
    count_time : float
        Total exposure time, seconds.
    deadtime / ph_open_cmd / ph_close_cmd / md :
        As in ``scan_edxd``.
    """
    _check_shutter_args(ph_open_cmd, ph_close_cmd)
    if start == stop:
        raise ValueError("start and stop must differ (ping-pong range).")
    if count_time <= 0:
        raise ValueError(f"count_time must be > 0, got {count_time}")

    _md = {
        "plan_name": "calib_scan",
        "detectors": [detector.name],
        "motors": [motor.name],
        "count_time": count_time,
        "start": start,
        "stop": stop,
    }
    _md.update(md or {})

    @bpp.stage_decorator([detector])
    @bpp.run_decorator(md=_md)
    def _inner():
        yield from bps.prepare(
            detector,
            TriggerInfo(livetime=count_time, deadtime=deadtime),
            wait=True,
        )
        print(f"  Calibration exposure {count_time:g} s; "
              f"{motor.name} ping-pong {start:g} <-> {stop:g}")
        yield from bps.trigger(detector, group=_EXPOSURE_GROUP)
        t0 = time.monotonic()
        target = start
        legs = 0
        while time.monotonic() - t0 < count_time:
            yield from bps.mv(motor, target)
            target = stop if target == start else start
            legs += 1
        print(f"  Count time reached after {legs} leg(s); waiting for exposure")
        yield from bps.wait(group=_EXPOSURE_GROUP)
        yield from bps.create("primary")
        yield from bps.read(detector)
        yield from bps.read(motor)
        yield from bps.save()

    initial = yield from bps.rd(motor)

    def _body():
        if ph_open_cmd is not None:
            yield from open_photon_shutter(ph_open_cmd)
        yield from _inner()

    def _cleanup():
        print(f"  Returning {motor.name} to {initial:g}")
        yield from bps.mv(motor, initial)
        if ph_close_cmd is not None:
            yield from close_photon_shutter(ph_close_cmd)

    return (yield from bpp.finalize_wrapper(_body(), _cleanup()))
