"""
Beam-availability signals and RunEngine suspenders.

Dissolves the legacy scripts' copy-pasted beam-dump handling (five identical
permit-wait loops across hex-acq-pyepics/techniques/edxd/, each polling
XF:27IDA-PPS{Sh:FE}Permit:Enbl-Sts every 20 s inside the scan): install the
suspenders once on the RunEngine and every plan gets suspend/resume behavior
for free, mid-scan included.

Legacy thresholds (lib_device_control's beam-dump/recover checks): the beam
counts as dumped below 100 mA and as recovered at 390 mA.
"""

from bluesky.suspenders import SuspendBoolLow, SuspendFloor
from ophyd_async.epics.core import epics_signal_r

RING_CURRENT_PV = "SR:OPS-BI{DCCT:1}I:Real-I"
FE_PERMIT_PV = "XF:27IDA-PPS{Sh:FE}Permit:Enbl-Sts"


class _OphydCallbackSignal:
    """Classic-ophyd subscribe facade over an ophyd-async signal.

    bluesky's suspenders install themselves with the pyepics-era callback
    API — ``subscribe(cb, event_type=..., run=...)`` / ``clear_sub(cb)``,
    calling back with a positional value — which ophyd-async signals do
    not speak: theirs delivers a ``{name: Reading}`` dict, and creating
    the subscription requires a running event loop, so it is marshaled
    onto the RunEngine's loop.  This shim maps between the two so the
    stock suspenders watch an ophyd-async signal unchanged.
    """

    def __init__(self, signal, loop):
        self._signal = signal
        self._loop = loop
        self._subs = {}
        self._last_value = None

    @property
    def name(self):
        return self._signal.name

    def get(self):
        # Blocking-get is only used for the suspender's justification text;
        # the last monitored value serves (an async get can't run in the
        # callback's thread).
        return self._last_value

    def _in_loop(self, call, *args):
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(call, *args)
        else:
            call(*args)

    def subscribe(self, callback, event_type=None, run=True):
        # The subscription fires immediately with the current reading,
        # which is the run=True behavior the suspender asks for.
        def wrapper(reading):
            (single,) = reading.values()
            self._last_value = single["value"]
            callback(single["value"])

        self._subs[callback] = wrapper
        self._in_loop(self._signal.subscribe_reading, wrapper)

    def clear_sub(self, callback):
        wrapper = self._subs.pop(callback, None)
        if wrapper is not None:
            self._in_loop(self._signal.clear_sub, wrapper)

    def __repr__(self):
        return f"{type(self).__name__}({self._signal!r})"


def make_beam_signals():
    """Ring current (mA) and front-end permit read-only signals."""
    ring_current = epics_signal_r(float, RING_CURRENT_PV, name="ring_current")
    fe_permit = epics_signal_r(int, FE_PERMIT_PV, name="fe_permit")
    return ring_current, fe_permit


def install_beam_suspenders(
    RE,
    ring_current,
    fe_permit,
    *,
    suspend_current: float = 100.0,
    resume_current: float = 390.0,
    sleep: float = 30.0,
):
    """
    Install ring-current and front-end-permit suspenders on *RE*.

    Parameters
    ----------
    RE : RunEngine
    ring_current / fe_permit : signal
        From ``make_beam_signals`` (or any readable/subscribable signal —
        the mock tests pass soft signals).
    suspend_current : float, optional
        Suspend when ring current drops below this (mA). Default 100.
    resume_current : float, optional
        Resume only once current is back above this (mA). Default 390 —
        the legacy scripts' recover threshold.
    sleep : float, optional
        Extra settle time (s) after the resume condition, before the plan
        continues. Default 30.

    Returns the two suspenders (current, permit) so a profile can remove
    them with ``RE.remove_suspender``.
    """
    if hasattr(ring_current, "subscribe_reading"):
        ring_current = _OphydCallbackSignal(ring_current, RE.loop)
    if hasattr(fe_permit, "subscribe_reading"):
        fe_permit = _OphydCallbackSignal(fe_permit, RE.loop)
    susp_current = SuspendFloor(
        ring_current,
        suspend_current,
        resume_thresh=resume_current,
        sleep=sleep,
    )
    susp_permit = SuspendBoolLow(fe_permit, sleep=sleep)
    RE.install_suspender(susp_current)
    RE.install_suspender(susp_permit)
    return susp_current, susp_permit
