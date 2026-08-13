"""
Batch composition of EDXD 1-D scans.

Equivalents of the old pyepics scripts:
    hex-acq-pyepics/techniques/edxd/run_multiple_scan_edxd.py
    hex-acq-pyepics/techniques/edxd/run_multiple_scan_edxd_custom_list.py

The originals re-launched scan_edxd.py as a subprocess per scan; here each
scan is a sub-plan producing its own run.  The custom-list variant steps an
outer motor through an explicit position list, running an inner 1-D scan
with per-position parameters at each stop (scalar parameters broadcast
across the list, as in the original).  Note the custom-list original was
dead at repo HEAD — it called lib functions (``fix_motor_name``) that exist
nowhere in the repo; passing devices instead of PV strings dissolves that
whole layer.

Both take a ``scan_plan`` override so orchestration is testable with stub
sub-plans (same pattern as plans/tomography/run_multiple_scans.py).
"""

from collections.abc import Sequence

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp

from .scan_edxd import scan_edxd


def repeat_scan_edxd(
    detector,
    motor,
    *,
    start: float,
    stop: float,
    num_points: int,
    count_time: float,
    num_scans: int,
    sleep_time: float = 0.0,
    scan_plan=None,
    **scan_kwargs,
):
    """
    Run the 1-D EDXD scan *num_scans* times, one run each.

    Parameters
    ----------
    detector / motor / start / stop / num_points / count_time :
        Passed through to ``scan_edxd``.
    num_scans : int
        How many scans (the original's ``-n``).
    sleep_time : float, optional
        Pause between scans, seconds (the original's ``--sleep``). Default 0.
    scan_plan : callable, optional
        The per-scan plan (defaults to ``scan_edxd``); stubbed in tests.
    **scan_kwargs :
        Extra keyword arguments for the per-scan plan (reset_position,
        shutter signals, md, ...).
    """
    if num_scans < 1:
        raise ValueError(f"num_scans must be >= 1, got {num_scans}")
    scan_plan = scan_plan or scan_edxd

    for index in range(num_scans):
        print(f"  EDXD batch scan {index + 1}/{num_scans}")
        yield from scan_plan(
            detector,
            motor,
            start=start,
            stop=stop,
            num_points=num_points,
            count_time=count_time,
            **scan_kwargs,
        )
        if sleep_time > 0 and index < num_scans - 1:
            yield from bps.sleep(sleep_time)


def _broadcast(value, n: int, name: str) -> list:
    """Scalar-or-list parameter handling, as in the original's -s/-e/-p/-d."""
    values = list(value) if isinstance(value, (Sequence, )) and not isinstance(value, str) else [value]
    if len(values) == 1:
        values = values * n
    if len(values) != n:
        raise ValueError(
            f"{name} has {len(values)} entries for {n} outer positions — "
            "give one value (broadcast) or exactly one per position."
        )
    return values


def scan_edxd_custom_list(
    detector,
    outer_motor,
    motor,
    *,
    outer_positions: Sequence[float],
    start,
    stop,
    num_points,
    count_time: float,
    descriptions=None,
    num_iterations: int = 1,
    sleep_time: float = 0.0,
    reset_outer: bool = True,
    scan_plan=None,
    **scan_kwargs,
):
    """
    Step *outer_motor* through *outer_positions*; inner 1-D scan at each.

    Parameters
    ----------
    detector : preparable/triggerable ophyd-async detector
    outer_motor : Movable
        The motor stepped through the explicit position list.
    motor : Movable
        The inner scan motor.
    outer_positions : sequence of float
        Outer stops (the original's --motor0-positions).
    start / stop / num_points :
        Inner-scan parameters; scalar (broadcast) or one per outer position.
    count_time : float
        Exposure time per inner-scan point, seconds.
    descriptions : str or sequence of str, optional
        Per-position scan description, recorded in each run's metadata.
    num_iterations : int, optional
        Repeat the whole list this many times. Default 1.
    sleep_time : float, optional
        Pause between inner scans, seconds. Default 0.
    reset_outer : bool, optional
        Restore the outer motor afterwards. Default True.
    scan_plan : callable, optional
        The inner plan (defaults to ``scan_edxd``); stubbed in tests.
    **scan_kwargs :
        Extra keyword arguments for the inner plan.
    """
    outer_positions = list(outer_positions)
    n = len(outer_positions)
    if n == 0:
        raise ValueError("outer_positions is empty.")
    if num_iterations < 1:
        raise ValueError(f"num_iterations must be >= 1, got {num_iterations}")
    starts = _broadcast(start, n, "start")
    stops = _broadcast(stop, n, "stop")
    nums = _broadcast(num_points, n, "num_points")
    descs = _broadcast(descriptions, n, "descriptions")
    scan_plan = scan_plan or scan_edxd

    initial_outer = (yield from bps.rd(outer_motor)) if reset_outer else None

    def _body():
        for iteration in range(num_iterations):
            print(f"  EDXD custom-list iteration {iteration + 1}/{num_iterations}")
            for j, outer_position in enumerate(outer_positions):
                yield from bps.mv(outer_motor, float(outer_position))
                print(f"   -> {outer_motor.name} = {outer_position:g}; "
                      f"inner scan {starts[j]:g} -> {stops[j]:g} ({nums[j]} pts)")
                inner_md = {"outer_motor": outer_motor.name,
                            "outer_position": outer_position}
                if descs[j] is not None:
                    inner_md["scan_description"] = descs[j]
                inner_md.update(scan_kwargs.get("md") or {})
                kwargs = {k: v for k, v in scan_kwargs.items() if k != "md"}
                yield from scan_plan(
                    detector,
                    motor,
                    start=starts[j],
                    stop=stops[j],
                    num_points=int(nums[j]),
                    count_time=count_time,
                    md=inner_md,
                    **kwargs,
                )
                if sleep_time > 0:
                    yield from bps.sleep(sleep_time)

    def _cleanup():
        if initial_outer is not None:
            print(f"  Returning {outer_motor.name} to {initial_outer:g}")
            yield from bps.mv(outer_motor, initial_outer)

    return (yield from bpp.finalize_wrapper(_body(), _cleanup()))
