"""
EDXD detector-arm + collimator geometry (ophyd-async).

Port of the pyepics script:
    hex-acq-pyepics/techniques/edxd/edxd_2theta_tilt.py

The coordinated move of the EDXD detector arm (X / Y / Rx) and its
collimator (X / Y-coarse / pitch) that realizes a requested 2-theta
diffraction angle.  Motors only — nothing here touches the GeRM detector
record, so this device is unaffected by the planned GeRM IOC replacement.

Setting the device to an angle (degrees):

    RE(bps.mv(edxd_geometry, 10.0))

1.  reads the arm Z position (set during alignment; never commanded here),
2.  computes the collimator correction angle
        delta = atan(slit_offset / (z - ds))
    and the Y / pitch / Y-coarse targets from the legacy formulas,
3.  launches all the moves together and waits for all of them (the old
    script used put_complete on each motor plus a wait-for-all loop).

Moving the arm out of the beam is a plain X translation — see
``plans.edxd.two_theta.edxd_move_out``.

WARNING — geometry constants: the defaults below are carried verbatim from
the legacy script (which also carries a stale "remember to change d1 after
April 10, 2025" note).  They are exposed as configuration signals so the
profile can correct them without a code change, and they must be confirmed
at the beamline before first real use.
"""

import asyncio
import math

from bluesky.protocols import Movable
from ophyd_async.core import (
    AsyncStatus,
    StandardReadable,
    StandardReadableFormat,
    soft_signal_rw,
)
from ophyd_async.epics.motor import Motor


class EDXDGeometry(StandardReadable, Movable):
    """
    The EDXD arm + collimator as one movable whose position is 2-theta (deg).

    Parameters
    ----------
    prefix:
        Beamline PV prefix; the motor suffixes are the fixed EDXD/collimator
        axis records under it.  Default is the HEX F-hutch prefix.
    """

    def __init__(self, prefix: str = "XF:27IDF-OP:1", name: str = "") -> None:
        with self.add_children_as_readables():
            self.det_x = Motor(prefix + "{EDXD:1-Ax:X}Mtr")
            self.det_y = Motor(prefix + "{EDXD:1-Ax:Y}Mtr")
            self.det_z = Motor(prefix + "{EDXD:1-Ax:Z}Mtr")
            self.det_rx = Motor(prefix + "{EDXD:1-Ax:Rx}Mtr")
            self.coll_x = Motor(prefix + "{CMT:1-Ax:X}Mtr")
            self.coll_y_coarse = Motor(prefix + "{CMT:1-Ax:Yc}Mtr")
            self.coll_pitch = Motor(prefix + "{Slt:CMT-Ax:Pitch}Mtr")
        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            # Legacy constants (edxd_2theta_tilt.py) — confirm at the beamline.
            self.d1 = soft_signal_rw(float, initial_value=425.0)
            self.ds = soft_signal_rw(float, initial_value=263.0)
            self.r_value = soft_signal_rw(float, initial_value=70.5)
            self.slit_offset = soft_signal_rw(float, initial_value=24.0)
            self.det_x_in = soft_signal_rw(float, initial_value=0.0)
            self.det_x_out = soft_signal_rw(float, initial_value=-270.0)
            self.coll_x_in = soft_signal_rw(float, initial_value=-54.0)
        super().__init__(name=name)

    @AsyncStatus.wrap
    async def set(self, value: float) -> None:
        two_theta = float(value)
        beta = math.radians(two_theta)
        d1, ds, r_value, slit_offset, det_x_in, coll_x_in = await asyncio.gather(
            self.d1.get_value(),
            self.ds.get_value(),
            self.r_value.get_value(),
            self.slit_offset.get_value(),
            self.det_x_in.get_value(),
            self.coll_x_in.get_value(),
        )
        z = await self.det_z.user_readback.get_value()
        if z <= ds:
            raise ValueError(
                f"EDXD arm Z readback ({z}) must be greater than ds ({ds}); "
                "the collimator correction atan(slit_offset / (z - ds)) is "
                "undefined otherwise. Is the arm aligned?"
            )
        delta = math.atan(slit_offset / (z - ds))
        det_y = -z * math.tan(beta)
        coll_pitch = two_theta - math.degrees(delta)
        coll_y_coarse = -(
            (d1 + r_value * math.sin(beta - delta) - (d1 - ds) * math.cos(beta - delta))
            * math.tan(beta)
            + (d1 - ds) * math.tan(beta - delta)
            - r_value * (1 - math.cos(beta - delta))
        )
        await asyncio.gather(
            self.det_x.set(det_x_in),
            self.det_rx.set(two_theta),
            self.det_y.set(det_y),
            self.coll_pitch.set(coll_pitch),
            self.coll_y_coarse.set(coll_y_coarse),
            self.coll_x.set(coll_x_in),
        )
