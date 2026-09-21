from pathlib import Path

# Create pyepics' initial CA context on the main thread before RunEngine/init_devices.
# Without this, ophyd-async's aioca backend attaches to a non-existent pyepics context
# and every connect in init_devices() times out on the first run (see PROGRESS.md).
import epics.ca
epics.ca.initialize_libca()

from bluesky import RunEngine
from bluesky.plan_stubs import mv, rd, wait
from bluesky.plans import scan
from ophyd_async.epics.adkinetix import KinetixDetector
from ophyd_async.epics.adcore import ADWriterFactory
from ophyd_async.fastcs.panda import HDFPanda

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
    panda1 = HDFPanda("XF:27ID1-ES{PANDA:1}:", path_provider=path_provider, name="panda")

def prepare_panda(num_images, exposure_time, deadtime):
    period = exposure_time + deadtime

    yield from bps.mv(
        panda1.pulse[2].pulses, num_images,
        panda1.pulse[2].step, period,
        panda1.pulse[2].width, exposure_time / 2,
    )


@bpp.stage_decorator([kinetix1])
@bpp.run_decorator()
def take_radiograph(
    num_image,
    exposure_time,
    num_iterations=1,
    sleep_time=0.0,
    deadtime=0.005,
):
    if num_image < 1 or num_iterations < 1:
        raise ValueError("Image and iteration counts must be positive.")
    if exposure_time <= 0 or deadtime < 0 or sleep_time < 0:
        raise ValueError(
            "Exposure must be positive; deadtime and sleep must be nonnegative."
        )

    trigger_info = TriggerInfo(
        trigger=DetectorTrigger.EXTERNAL_EDGE,
        livetime=exposure_time,
        deadtime=deadtime,
        exposures_per_collection=1,
        collections_per_event=num_image,
        number_of_events=num_iterations,
    )

    def acquisition():
        yield from bps.mv(panda1.bits.a, 0)
        yield from prepare_panda(
            num_image, exposure_time, deadtime
        )

        # Prepare all images once; keep the same writer open.
        yield from bps.prepare(
            kinetix1, trigger_info, wait=True
        )

        # Each kickoff/complete pair handles one batch.
        # Set this AFTER prepare(), which resets this value.
        yield from bps.mv(kinetix1.events_to_kickoff, 1)

        yield from bps.declare_stream(
            kinetix1, name="primary"
        )
        yield from bps.sleep(1.0)

        for iteration in range(num_iterations):
            yield from bps.mv(panda1.bits.a, 0)

            yield from bps.kickoff_all(
                kinetix1, wait=True
            )
            yield from bps.mv(panda1.bits.a, 1)

            # Wait for this batch and publish its data references.
            yield from bps.collect_while_completing(
                [kinetix1],
                [kinetix1],
                flush_period=1,
            )

            yield from bps.mv(panda1.bits.a, 0)

            if iteration < num_iterations - 1 and sleep_time:
                yield from bps.sleep(sleep_time)

    yield from bpp.finalize_wrapper(
        acquisition(),
        bps.mv(panda1.bits.a, 0),
    )

