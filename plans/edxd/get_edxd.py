"""
Single EDXD exposure.

Equivalent of the old pyepics script:
    hex-acq-pyepics/techniques/edxd/get_edxd.py

One *count_time* exposure into ``primary``.  The original's ``-c 0`` mode
(read the stale MCA array without triggering) is NOT ported: a generic
read-without-trigger has no meaning for an ophyd-async detector whose
reading comes from its prepared writer path, and whether the mode needs to
survive at all is an open question for the beamline (it would become a
device-side capability of the GeRM detector when that lands).  Passing
``count_time=0`` raises with that explanation rather than guessing.
"""

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
from ophyd_async.core import TriggerInfo

from lib.shutter import close_photon_shutter, open_photon_shutter

from .scan_edxd import _check_shutter_args


def get_edxd(
    detector,
    *,
    count_time: float,
    deadtime: float = 0.002,
    ph_open_cmd=None,
    ph_close_cmd=None,
    md: dict | None = None,
):
    """
    Take one *count_time* exposure.

    Parameters
    ----------
    detector : preparable/triggerable ophyd-async detector
    count_time : float
        Exposure time, seconds. Must be > 0 (see module docstring for the
        original's stale-read ``-c 0`` mode).
    deadtime / ph_open_cmd / ph_close_cmd / md :
        As in ``scan_edxd``.
    """
    _check_shutter_args(ph_open_cmd, ph_close_cmd)
    if count_time == 0:
        raise NotImplementedError(
            "the original's '-c 0' stale-MCA read is not ported — whether it "
            "is still needed is an open question for the beamline; if it is, "
            "it becomes a device-side read on the GeRM detector."
        )
    if count_time < 0:
        raise ValueError(f"count_time must be > 0, got {count_time}")

    _md = {
        "plan_name": "get_edxd",
        "detectors": [detector.name],
        "count_time": count_time,
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
        print(f"  EDXD single exposure: {count_time:g} s")
        yield from bps.trigger_and_read([detector])

    def _body():
        if ph_open_cmd is not None:
            yield from open_photon_shutter(ph_open_cmd)
        yield from _inner()

    def _cleanup():
        if ph_close_cmd is not None:
            yield from close_photon_shutter(ph_close_cmd)

    return (yield from bpp.finalize_wrapper(_body(), _cleanup()))
