
from pathlib import Path

# Create pyepics' initial CA context on the main thread before RunEngine/init_devices.
# Without this, ophyd-async's aioca backend attaches to a non-existent pyepics context
# and every connect in init_devices() times out on the first run (see PROGRESS.md).
import epics.ca
epics.ca.initialize_libca()

from bluesky import RunEngine
from bluesky.plan_stubs import mv, rd, wait

from ophyd_async.epics.adkinetix import KinetixDetector
from ophyd_async.epics.adcore import ADWriterFactory
from ophyd_async.epics.motor import Motor
from ophyd_async.fastcs.panda import HDFPanda

import bluesky.plans as bp
import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp

from ophyd_async.core import TriggerInfo, init_devices, AutoIncrementingPathProvider, StaticFilenameProvider, DetectorTrigger

kinetix_prefix = "XF:27ID1-BI{Kinetix-Det:1}"

path_provider = AutoIncrementingPathProvider(
    filename_provider = StaticFilenameProvider("img"),
    base_directory_path=Path("/nsls2/data/hex/proposals/commissioning/pass-314022/tmp/test_kinetix/"),
    base_name = "scan",
    max_digits=5,
    create_dir_depth=5)

RE = RunEngine(call_returns_result=True)

# define any axis (Z is in beamline, X is left/right, and Y is up/down)
# how can I specify an axis for translation scans and only translate along that axis?
with init_devices():
    kinetix1 = KinetixDetector(kinetix_prefix,
                              ADWriterFactory.hdf(path_provider, writer_suffix="HDF1:"),
                              name="kinetix1")
    panda1 = HDFPanda("XF:27ID1-ES{PANDA:1}:", path_provider=path_provider, name="panda")

    motor_x1 = Motor("XF:27IDF-OP:1{SMPL:1-Ax:X1}:", name="motor_x1")
    #motor_y1 = Motor("XF:27IDF-OP:1{SMPL:1-Ax:Y1}:", name="motor_y1")
    motor_z1 = Motor("XF:27IDF-OP:1{SMPL:1-Ax:Z1}:", name="motor_z1")

# Map an axis name to its motor. `scan` moves ONLY the motor(s) you pass it,
# so scanning a single axis keeps every other axis stationary.
# AXES = {"x": motor_x1, "y": motor_y1, "z": motor_z1}
AXES = {"x": motor_x1, "z": motor_z1}

# Example motor X1 PVs for reference:
# High limit of motor:  XF:27IDF-OP:1{SMPL:1-Ax:X1}Mtr.HLM
# Low limit of motor:  XF:27IDF-OP:1{SMPL:1-Ax:X1}Mtr.LLM
# Max velocity of motor:  XF:27IDF-OP:1{SMPL:1-Ax:X1}Mtr.VMAX
# Speed of motor: XF:27IDF-OP:1{SMPL:1-Ax:X1}Mtr.VELO
# Base Speed of motor (minimum speed of motor): XF:27IDF-OP:1{SMPL:1-Ax:X1}Mtr.VBAS
# Acceleration of motor: XF:27IDF-OP:1{SMPL:1-Ax:X1}Mtr.ACCL


def translation_scan(axis, start, stop, num_images, exposure_time,
                     deadtime=0.005, detector=kinetix1, panda=panda1, lead_margin=1.5):
    """PandA-triggered constant-velocity fly scan along ONE axis.

    The motor sweeps at a fixed velocity while the PandA emits ``num_images``
    evenly spaced pulses (one per position) that externally trigger the
    detector.

    axis          : 'x' (left/right), 'y' (up/down) or 'z' (along beam). 'y' is currently disabled.
    start, stop   : scan endpoints in motor egu (e.g. mm).
    num_images    : number of frames / trigger positions.
    exposure_time : detector livetime per frame (s).
    deadtime      : minimum detector dead time between frames (s).

    Kinematics: step_size = |stop-start| / num_images; the frame period is the
    shortest the detector allows (exposure + deadtime), giving the fastest
    velocity that respects the exposure. That velocity is capped at the motor's
    max speed; if the cap engages the frame period is stretched to match so the
    pulse train and the moving stage stay synchronised.
    """

    motor = AXES[axis]

    if num_images < 1:
        raise ValueError("num_images must be >= 1")
    if exposure_time <= 0:
        raise ValueError("exposure_time must be > 0")
    if start == stop:
        raise ValueError("start and stop must differ")

    delta = abs(stop - start)
    direction = 1.0 if stop > start else -1.0
    step_size = delta / num_images

    frame_period = exposure_time + deadtime
    velocity = step_size / frame_period
    max_velocity = yield from bps.rd(motor.max_velocity)
    if max_velocity and velocity > max_velocity:
        velocity = max_velocity
        frame_period = step_size / velocity

    # Run-up distance so the stage reaches constant velocity before the first
    # trigger (accel distance = 1/2 * v * t_accel), plus a safety margin.
    accel_time = yield from bps.rd(motor.acceleration_time)
    run_up = lead_margin * 0.5 * velocity * accel_time
    entry = start - direction * run_up
    exit_pos = stop + direction * run_up

    # The stage physically reaches the run-up points, not just start/stop, so
    # validate the whole travel span against the motor soft limits (.LLM/.HLM).
    low_limit = yield from bps.rd(motor.low_limit_travel)
    high_limit = yield from bps.rd(motor.high_limit_travel)
    travel_lo = min(entry, exit_pos)
    travel_hi = max(entry, exit_pos)
    if (low_limit, high_limit) != (0.0, 0.0) and (
        travel_lo < low_limit or travel_hi > high_limit
    ):
        raise ValueError(
            f"{motor.name}: travel [{travel_lo:.4g}, {travel_hi:.4g}] "
            f"(start/stop {start}/{stop} plus run-up) is outside soft limits "
            f"[{low_limit}, {high_limit}]"
        )

    original_velocity = yield from bps.rd(motor.velocity)

    trigger_info = TriggerInfo(
        trigger=DetectorTrigger.EXTERNAL_EDGE,
        livetime=exposure_time,
        deadtime=deadtime,
        number_of_events=num_images,
    )

    def _fly():
        # Move to the run-up entry point at the original (non-scan) speed.
        yield from bps.mv(motor.velocity, original_velocity)
        yield from bps.mv(motor, entry)

        # Arm the detector and the PandA pulse train (gate held closed).
        yield from bps.mv(panda.bits.a, 0)
        yield from bps.mv(
            panda.pulse[2].pulses, num_images,
            panda.pulse[2].step, frame_period,
            panda.pulse[2].width, exposure_time / 2,
        )
        yield from bps.stage_all(detector)
        yield from bps.prepare(detector, trigger_info, wait=True)
        yield from bps.declare_stream(detector, name="primary")
        yield from bps.kickoff_all(detector, wait=True)

        # Sweep at scan velocity; open the gate the instant we cross `start`.
        yield from bps.mv(motor.velocity, velocity)
        yield from bps.abs_set(motor, exit_pos, group="fly_sweep")
        pos = yield from bps.rd(motor)
        while (pos - start) * direction < 0:
            yield from bps.sleep(0.01)
            pos = yield from bps.rd(motor)
        yield from bps.mv(panda.bits.a, 1)

        yield from bps.collect_while_completing([detector], [detector], flush_period=1)
        yield from bps.wait(group="fly_sweep")

    def _cleanup():
        # Close the gate and restore the motor's original velocity even on error.
        yield from bps.mv(panda.bits.a, 0)
        yield from bps.mv(motor.velocity, original_velocity)
        yield from bps.unstage_all(detector)

    yield from bpp.finalize_wrapper(bpp.run_wrapper(_fly()), _cleanup())


# Example: fly X from 0 to 10 mm, 4 images, 0.1 s exposure (Y and Z stay put):
#   RE(translation_scan("x", 0, 10, 4, exposure_time=0.1))

