from pathlib import Path
from bluesky import RunEngine
from bluesky.plan_stubs import mv, rd
from bluesky.plans import scan
from ophyd_async.epics.adkinetix import KinetixDetector
from ophyd_async.epics.adcore import ADWriterFactory

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

with init_devices():
    kinetix1 = KinetixDetector(kinetix_prefix,
                              ADWriterFactory.hdf(path_provider, writer_suffix="HDF1:"),
                              name="kinetix1")

@bpp.stage_decorator([kinetix1])
@bpp.run_decorator()
def take_radiograph(num_image, exposure_time, num_iterations=1, sleep_time=0.0):
    trigger_info = TriggerInfo(
        trigger=DetectorTrigger.INTERNAL,
        livetime=exposure_time,
        deadtime=0.005,
        exposures_per_collection=1,
        collections_per_event=num_image,
        number_of_events=1)

    # yield from bps.prepare(kinetix1, trigger_info, wait=True) # For 1
    for _ in range(num_iterations):
        yield from bps.prepare(kinetix1, trigger_info, wait=True)

    # yield from bps.declare_stream(kinetix1, name ="primary")

    for _ in range(num_iterations):
        yield from bps.trigger_and_read([kinetix1], name="primary")
        if sleep_time > 0.0:
            yield from bps.sleep(sleep_time)









