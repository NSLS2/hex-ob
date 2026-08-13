"""
1-D EDXD step-scan plan.

Equivalent of the old pyepics script:
    hex-acq-pyepics/techniques/edxd/scan_edxd.py

What this plan does
-------------------
1.  Optionally opens the photon shutter (pass both shutter command signals;
    front-end/beam-dump handling is the RunEngine suspenders' job — see
    lib/beam.py).
2.  Steps *motor* through linspace(start, stop, num_points); at each point
    triggers one *count_time* exposure into the ``primary`` stream (motor
    readback recorded per point).  start == stop repeats exposures at one
    position, like the original.
3.  Restores the motor to its initial position (the original's ``-r 1``
    default; pass ``reset_position=False`` for the ``-r 0`` behavior of
    leaving it at stop) and closes the shutter if it opened it.

The detector is any ophyd-async detector that can be prepared with a
TriggerInfo and triggered — nothing here asserts the GeRM record surface,
so the same plan runs against the current GeRM IOC's device, its
replacement, or a mock.  The old script's tif/HDF writing dissolves into
the detector's own writer + documents; the ~80-PV motor-position metadata
dump becomes the RunEngine baseline (profile-side, ``sd.baseline``).
"""

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import numpy as np
from ophyd_async.core import TriggerInfo

from lib.shutter import close_photon_shutter, open_photon_shutter


def _positions(start: float, stop: float, num_points: int) -> np.ndarray:
    if num_points < 1:
        raise ValueError(f"num_points must be >= 1, got {num_points}")
    if start == stop:
        return np.full(num_points, start)
    if num_points <= 1:
        raise ValueError(
            "num_points must be > 1 when start != stop (one exposure per position)."
        )
    return np.linspace(start, stop, num_points)


def _check_shutter_args(ph_open_cmd, ph_close_cmd) -> None:
    if (ph_open_cmd is None) != (ph_close_cmd is None):
        raise ValueError(
            "pass both ph_open_cmd and ph_close_cmd, or neither "
            "(shutterless operation)."
        )


def scan_edxd(
    detector,
    motor,
    *,
    start: float,
    stop: float,
    num_points: int,
    count_time: float,
    reset_position: bool = True,
    rest_time: float = 0.0,
    deadtime: float = 0.002,
    ph_open_cmd=None,
    ph_close_cmd=None,
    md: dict | None = None,
):
    """
    Step *motor* from *start* to *stop*, one *count_time* exposure per point.

    Parameters
    ----------
    detector : preparable/triggerable ophyd-async detector
    motor : Movable
        The motor to scan (the old script took a PV name).
    start / stop : float
        Scan range; start == stop repeats exposures at one position.
    num_points : int
        Number of positions.
    count_time : float
        Exposure (count) time per point, seconds.
    reset_position : bool, optional
        Return the motor to its pre-scan position afterwards (old ``-r``,
        default True).
    rest_time : float, optional
        Settle time after each move, seconds. Default 0.
    deadtime : float, optional
        Detector deadtime handed to TriggerInfo. Default 2 ms.
    ph_open_cmd / ph_close_cmd : signal, optional
        Photon-shutter command signals (write 1 to actuate). Omit both to
        run shutterless.
    md : dict, optional
        Extra run metadata.
    """
    _check_shutter_args(ph_open_cmd, ph_close_cmd)
    positions = _positions(start, stop, num_points)
    if count_time <= 0:
        raise ValueError(f"count_time must be > 0, got {count_time}")

    _md = {
        "plan_name": "scan_edxd",
        "detectors": [detector.name],
        "motors": [motor.name],
        "count_time": count_time,
        "start": start,
        "stop": stop,
        "num_points": num_points,
        "rest_time": rest_time,
        "reset_position": reset_position,
        "hints": {"dimensions": [([motor.name], "primary")]},
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
        print(f"  EDXD 1-D scan of {motor.name}: {start:g} -> {stop:g} "
              f"({num_points} points, {count_time:g} s counts)")
        for position in positions:
            yield from bps.mv(motor, float(position))
            if rest_time > 0:
                yield from bps.sleep(rest_time)
            yield from bps.trigger_and_read([detector, motor])

    initial = (yield from bps.rd(motor)) if reset_position else None

    def _body():
        if ph_open_cmd is not None:
            yield from open_photon_shutter(ph_open_cmd)
        yield from _inner()

    def _cleanup():
        if initial is not None:
            print(f"  Returning {motor.name} to {initial:g}")
            yield from bps.mv(motor, initial)
        if ph_close_cmd is not None:
            yield from close_photon_shutter(ph_close_cmd)

    return (yield from bpp.finalize_wrapper(_body(), _cleanup()))
