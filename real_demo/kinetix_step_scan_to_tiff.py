
from pathlib import Path

# Create pyepics' initial CA context on the main thread before RunEngine/init_devices.
# Without this, ophyd-async's aioca backend attaches to a non-existent pyepics context
# and every connect in init_devices() times out on the first run (see PROGRESS.md).
import epics.ca
epics.ca.initialize_libca()

from bluesky import RunEngine

from ophyd_async.epics.adkinetix import KinetixDetector
# from ophyd_async.epics.adcore import ADWriterFactory
from ophyd_async.epics.motor import Motor

# testing to see if this resolves 10 second default timeout issue
from ophyd_async.epics.adcore import ADMultipartDataLogic, ADWriterFactory, NDPluginFileIO
from ophyd_async.epics.core import stop_busy_record

import bluesky.plans as bp
import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp

from ophyd_async.core import init_devices, AutoIncrementingPathProvider, StaticFilenameProvider

kinetix_prefix = "XF:27ID1-BI{Kinetix-Det:1}"

path_provider = AutoIncrementingPathProvider(
    filename_provider = StaticFilenameProvider("img"),
    base_directory_path=Path("/nsls2/data/hex/proposals/commissioning/pass-314022/tmp/test_kinetix/"),
    base_name = "scan",
    max_digits=5,
    create_dir_depth=5)

RE = RunEngine(call_returns_result=True)

# Adding to set a slow close logic for TIFF writer to avoid default 10 second timeout issue
# How this works:
# Inheritance keeps everything else the same: prepare_unbounded, file templates, stream resources.
# You replace only stop(), and the only difference is timeout=60.
# It must be async def because the detector `await`s it.
class SlowCloseTiffDataLogic(ADMultipartDataLogic):
    async def stop(self):
        await stop_busy_record(self.writer.capture, timeout=60)


# This copies what ADWriterFactory.tiff() does inside the library, with your class swapped in. 
# You can compare it with the library's tiff() staticmethod in _data_logic.py.
tiff_writer = ADWriterFactory(
    writer_cls=NDPluginFileIO,
    writer_suffix="TIFF1:",
    writer_name="tiff",
    datakey_suffix="",
    array_description=None,
    data_logic_factory=lambda writer, desc, driver, plugins: SlowCloseTiffDataLogic(
        array_description=desc,
        path_provider=path_provider,
        writer=writer,
        extension=".tiff",
        mimetype="multipart/related;type=image/tiff",
    ),
)

with init_devices():
    kinetix1 = KinetixDetector(kinetix_prefix,
                            #   ADWriterFactory.tiff(path_provider, writer_suffix="TIFF1:"),
                              tiff_writer,
                              name="kinetix1")

    motor_x1 = Motor("XF:27IDF-OP:1{SMPL:1-Ax:X1}Mtr", name="motor_x1")
    motor_z1 = Motor("XF:27IDF-OP:1{SMPL:1-Ax:Z1}Mtr", name="motor_z1")

AXES = {"x": motor_x1, "z": motor_z1}


def translation_step_scan(axis, start, stop, num_images, exposure_time):   

    motor = AXES[axis]
    yield from bps.mv(kinetix1.driver.acquire_time, exposure_time)
    yield from bp.scan([kinetix1], motor, start, stop, num_images)


# Example usage:
# yield from translation_step_scan('x', 0, 10, 1, 0.1)
