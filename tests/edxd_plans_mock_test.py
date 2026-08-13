"""
Full-plan mock tests for the EDXD plan family (plans/edxd/).

Every plan runs END-TO-END under the RunEngine against the mock beamline —
deliberately using the mock KINETIX as the detector: the plans are
device-agnostic (nothing asserts the GeRM record surface), and running them
against a completely different detector class is the proof.

Run from the hex-ob root:  python tests/edxd_plans_mock_test.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bluesky.plan_stubs as bps
from mock_beamline import MockBeamline

from plans.edxd import (
    calib_scan,
    get_edxd,
    repeat_scan_edxd,
    scan_2d_average,
    scan_edxd,
    scan_edxd_2d,
    scan_edxd_custom_list,
)

try:
    from ophyd_async.testing import callback_on_mock_put
except ImportError:
    from ophyd_async.core._mock_signal_utils import callback_on_mock_put


def rb(signal):
    return asyncio.run(signal.get_value())


def motor_series(bl, motor_name):
    """The motor's readback per primary event, in order."""
    descriptors = {
        doc["uid"]: doc["name"] for name, doc in bl.docs if name == "descriptor"
    }
    return [
        doc["data"][motor_name]
        for name, doc in bl.docs
        if name == "event" and descriptors[doc["descriptor"]] == "primary"
    ]


def start_plan(gen):
    """Drive to the first message (validation happens there), then close."""
    msg = next(gen)
    try:
        gen.close()
    except RuntimeError:
        pass
    return msg


def expect_value_error(gen, fragment):
    try:
        start_plan(gen)
    except ValueError as exc:
        assert fragment in str(exc), exc
    else:
        raise AssertionError(f"expected ValueError mentioning {fragment!r}")


def main() -> None:
    bl = MockBeamline()

    # -- scan_edxd: events, order, restore ----------------------------------
    bl.reset()
    bl.RE(bps.mv(bl.rot_stage, 2.0))
    bl.RE(scan_edxd(
        bl.detector, bl.rot_stage,
        start=0.0, stop=9.0, num_points=4, count_time=0.01,
    ))
    assert bl.last_stop()["exit_status"] == "success"
    assert bl.events_by_stream() == {"primary": 4}, bl.events_by_stream()
    assert motor_series(bl, "rot_stage") == [0.0, 3.0, 6.0, 9.0]
    assert rb(bl.rot_stage.user_readback) == 2.0, "reset_position should restore"
    print("PASS  scan_edxd (4 primary, linspace order, restored)")

    # reset_position=False leaves the motor at stop, with shutter dance
    bl.reset()
    bl.RE(scan_edxd(
        bl.detector, bl.rot_stage,
        start=0.0, stop=9.0, num_points=4, count_time=0.01,
        reset_position=False,
        ph_open_cmd=bl.ph_open_cmd, ph_close_cmd=bl.ph_close_cmd,
    ))
    assert rb(bl.rot_stage.user_readback) == 9.0
    assert rb(bl.ph_close_cmd) == 1, "shutter close command not written"
    print("PASS  scan_edxd (reset_position=False, shutter commands written)")

    # start == stop repeats at one position
    bl.reset()
    bl.RE(scan_edxd(
        bl.detector, bl.rot_stage,
        start=5.0, stop=5.0, num_points=3, count_time=0.01,
    ))
    assert motor_series(bl, "rot_stage") == [5.0, 5.0, 5.0]
    print("PASS  scan_edxd (start == stop repeats)")

    # validation
    expect_value_error(
        scan_edxd(bl.detector, bl.rot_stage,
                  start=0.0, stop=1.0, num_points=1, count_time=0.01),
        "num_points",
    )
    expect_value_error(
        scan_edxd(bl.detector, bl.rot_stage,
                  start=0.0, stop=1.0, num_points=2, count_time=0.0),
        "count_time",
    )
    expect_value_error(
        scan_edxd(bl.detector, bl.rot_stage,
                  start=0.0, stop=1.0, num_points=2, count_time=0.01,
                  ph_open_cmd=bl.ph_open_cmd),
        "both",
    )
    print("PASS  scan_edxd (validation raises)")

    # -- scan_edxd_2d: row-major raster, rewind, restore, iterations --------
    bl.reset()
    bl.RE(bps.mv(bl.rot_stage, 0.0, bl.sample_x, 0.0))
    bl.RE(scan_edxd_2d(
        bl.detector, bl.sample_x, bl.rot_stage,
        start1=-1.0, stop1=1.0, num_points1=3,
        start2=0.0, stop2=10.0, num_points2=2,
        count_time=0.01, num_iterations=2,
    ))
    stops = [doc for name, doc in bl.docs if name == "stop"]
    assert len(stops) == 2 and all(s["exit_status"] == "success" for s in stops)
    # 2 iterations x (2 rows x 3 cols): inner rewinds each row, no snake
    assert motor_series(bl, "sample_x") == [-1.0, 0.0, 1.0] * 4
    assert motor_series(bl, "rot_stage") == ([0.0] * 3 + [10.0] * 3) * 2
    assert rb(bl.sample_x.user_readback) == 0.0
    assert rb(bl.rot_stage.user_readback) == 0.0
    print("PASS  scan_edxd_2d (row-major, rewind, 2 runs, both restored)")

    # degenerate outer range respects num_points2 (the legacy bug this fixes)
    bl.reset()
    bl.RE(scan_edxd_2d(
        bl.detector, bl.sample_x, bl.rot_stage,
        start1=-1.0, stop1=1.0, num_points1=2,
        start2=5.0, stop2=5.0, num_points2=3,
        count_time=0.01,
    ))
    assert bl.events_by_stream() == {"primary": 6}, bl.events_by_stream()
    print("PASS  scan_edxd_2d (start2 == stop2 uses num_points2: 3 rows)")

    # -- scan_2d_average: velocity choreography, restore --------------------
    velocity_puts: list[float] = []
    callback_on_mock_put(
        bl.rot_stage.velocity, lambda value, **kw: velocity_puts.append(value)
    )
    bl.reset()
    bl.RE(bps.mv(bl.sample_x, 0.0, bl.rot_stage, 0.0))
    velocity_puts.clear()
    bl.RE(scan_2d_average(
        bl.detector, bl.sample_x, bl.rot_stage,
        start1=0.0, stop1=2.0, num_points1=3,
        start2=0.0, stop2=1.0,
        count_time=0.2, travel_velocity=0.5,
    ))
    assert bl.last_stop()["exit_status"] == "success"
    assert bl.events_by_stream() == {"primary": 3}, bl.events_by_stream()
    assert motor_series(bl, "sample_x") == [0.0, 1.0, 2.0]
    # per point: travel (0.5) for the rewind, then sweep (span/count = 5.0);
    # final 0.5 is the cleanup restore
    assert velocity_puts == [0.5, 5.0] * 3 + [0.5], velocity_puts
    assert rb(bl.sample_x.user_readback) == 0.0
    assert rb(bl.rot_stage.user_readback) == 0.0
    assert rb(bl.rot_stage.velocity) == 0.5
    print("PASS  scan_2d_average (velocity travel/sweep per point, restored)")

    expect_value_error(
        scan_2d_average(bl.detector, bl.sample_x, bl.rot_stage,
                        start1=0.0, stop1=1.0, num_points1=2,
                        start2=3.0, stop2=3.0, count_time=0.2),
        "start2",
    )
    print("PASS  scan_2d_average (degenerate sweep range raises)")

    # -- calib_scan: single event, ping-pong visited both limits ------------
    bl.reset()
    bl.RE(bps.mv(bl.sample_x, 0.5))
    bl.reset()
    bl.RE(calib_scan(
        bl.detector, bl.sample_x,
        start=-1.0, stop=1.0, count_time=0.25,
    ))
    assert bl.last_stop()["exit_status"] == "success"
    assert bl.events_by_stream() == {"primary": 1}, bl.events_by_stream()
    # the single event carries the motor reading too
    series = motor_series(bl, "sample_x")
    assert len(series) == 1
    assert rb(bl.sample_x.user_readback) == 0.5, "calib_scan should restore"
    print("PASS  calib_scan (1 primary, restored)")

    # -- get_edxd ------------------------------------------------------------
    bl.reset()
    bl.RE(get_edxd(bl.detector, count_time=0.01))
    assert bl.last_stop()["exit_status"] == "success"
    assert bl.events_by_stream() == {"primary": 1}
    print("PASS  get_edxd (1 primary)")

    try:
        start_plan(get_edxd(bl.detector, count_time=0))
    except NotImplementedError as exc:
        assert "stale-MCA" in str(exc)
    else:
        raise AssertionError("count_time=0 should raise NotImplementedError")
    print("PASS  get_edxd (stale-read mode refused, not guessed)")

    # -- batch runners (stub sub-plans, orchestration only) ------------------
    calls: list[tuple] = []

    def stub(detector, motor, *, start, stop, num_points, count_time, md=None,
             **kwargs):
        calls.append((start, stop, num_points,
                      (md or {}).get("outer_position"),
                      (md or {}).get("scan_description")))
        yield from bps.null()

    calls.clear()
    bl.RE(repeat_scan_edxd(
        bl.detector, bl.rot_stage,
        start=0.0, stop=1.0, num_points=5, count_time=0.01,
        num_scans=3, sleep_time=0.01, scan_plan=stub,
    ))
    assert calls == [(0.0, 1.0, 5, None, None)] * 3, calls
    print("PASS  repeat_scan_edxd (3 sub-scans)")

    calls.clear()
    bl.RE(bps.mv(bl.rot_stage, 0.0))
    bl.RE(scan_edxd_custom_list(
        bl.detector, bl.rot_stage, bl.sample_x,
        outer_positions=[10.0, 20.0],
        start=[0.0, -1.0], stop=1.0, num_points=[3, 5], count_time=0.01,
        descriptions=["a", "b"], scan_plan=stub,
    ))
    assert calls == [
        (0.0, 1.0, 3, 10.0, "a"),
        (-1.0, 1.0, 5, 20.0, "b"),
    ], calls
    assert rb(bl.rot_stage.user_readback) == 0.0, "outer motor restored"
    print("PASS  scan_edxd_custom_list (per-position params, outer restored)")

    expect_value_error(
        scan_edxd_custom_list(
            bl.detector, bl.rot_stage, bl.sample_x,
            outer_positions=[10.0, 20.0],
            start=[0.0, 1.0, 2.0], stop=1.0, num_points=3, count_time=0.01,
        ),
        "start",
    )
    print("PASS  scan_edxd_custom_list (length-mismatch raises)")

    print("\nALL PASS")


if __name__ == "__main__":
    main()
