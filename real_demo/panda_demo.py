from ophyd_async.fastcs.panda import HDFPanda
from bluesky import RunEngine
from bluesky.run_engine import autoawait_in_bluesky_event_loop
from ophyd_async.core import init_devices, FilenameProvider, YMDPathProvider, UUIDFilenameProvider, StaticPathProvider, AutoIncrementingPathProvider
from bluesky.plan_stubs import rd, mv, mvr
from pathlib import Path

RE = RunEngine(call_returns_result=True)
autoawait_in_bluesky_event_loop()

class CustomFilenameProvider(FilenameProvider):
    
    scan_number = 0
    
    def __call__(self, datakey_name: str | None = None):
        self.scan_number += 1
        return f"{datakey_name}_scan_{self.scan_number}"

filename_provider = UUIDFilenameProvider()
#path_provider = StaticPathProvider(filename_provider, Path("/tmp/"))
#path_provider = YMDPathProvider(UUIDFilenameProvider(), Path("/tmp/"))
path_provider = AutoIncrementingPathProvider(CustomFilenameProvider(), Path("/tmp/"))

with init_devices():
    panda = HDFPanda("XF:27ID1-ES{PANDA:1}:", path_provider=path_provider, name="panda")
    
def my_plan():
    num_pulses = yield from rd(panda.pulse[2].pulses)
    print(num_pulses)
    return "Hello AJ"    

def move_panda(steps: int):
    yield from mvr(panda.pulse[2].pulses, steps)
    
from ophyd_async.core import Device, DeviceVector
    
PIPE = "│"
ELBOW = "└──"
TEE = "├──"
PIPE_PREFIX = "│   "
SPACE_PREFIX = "    "


def _get_children(device: Device) -> list[tuple[str, Device]]:
    """
    Supplementary method for building the tree view of a device.
    Return the (name, child) pairs of a device, sorted for display.
    """
    children = [
        (name, child) for name, child in device.children() if isinstance(child, Device)
    ]
    if isinstance(device, DeviceVector):
        # DeviceVector children are stringified integer indices.
        return sorted(children, key=lambda item: int(item[0]))
    return sorted(children, key=lambda item: item[0])


def _make_tree_body(tree: list[str], device: Device, prefix=""):
    """
    Supplementary method for building the tree view of a device.
    Create the tree body.
    """
    entries = _get_children(device)
    last_index = len(entries) - 1
    for index, (name, child) in enumerate(entries):
        if index == 0:
            tree.append(prefix + PIPE)
        connector = ELBOW if index == last_index else TEE
        tree.append(f"{prefix}{connector} {name}")
        child_prefix = prefix + (
            SPACE_PREFIX if index == last_index else PIPE_PREFIX
        )
        _make_tree_body(tree, child, prefix=child_prefix)


def print_device_tree(device: Device, indent: int = 0) -> None:
    """Print the device tree for a given device.

    Parameters
    ----------
    device : Device
        The device whose tree is to be printed.
    indent : int
        The indentation level for the current device.
    """
    x = []
    _make_tree_body(x, device)
    print("\n".join(x))


# list(panda.children())
# Out[33]: 
# [('pulse', <ophyd_async.core._device.DeviceVector at 0x7eff12d94f50>),
#  ('seq', <ophyd_async.core._device.DeviceVector at 0x7eff12d95550>),
#  ('pcomp', <ophyd_async.core._device.DeviceVector at 0x7eff12d95ee0>),
#  ('pcap', <ophyd_async.fastcs.panda._block.PcapBlock at 0x7eff1378a8a0>),
#  ('data', <ophyd_async.fastcs.panda._block.DataBlock at 0x7eff12d72390>),
#  ('bits', <ophyd_async.core._device.Device at 0x7eff12cedd30>),
#  ('calc', <ophyd_async.core._device.DeviceVector at 0x7eff12cedbe0>),
#  ('clock', <ophyd_async.core._device.DeviceVector at 0x7eff306043e0>),
#  ('counter', <ophyd_async.core._device.DeviceVector at 0x7eff30604c80>),
#  ('div', <ophyd_async.core._device.DeviceVector at 0x7eff30606870>),
#  ('filter', <ophyd_async.core._device.DeviceVector at 0x7eff30606960>),
#  ('fmc_in', <ophyd_async.core._device.Device at 0x7eff30605d30>),
#  ('fmc_out', <ophyd_async.core._device.Device at 0x7eff30605760>),
#  ('inenc', <ophyd_async.core._device.DeviceVector at 0x7eff306063f0>),
#  ('lut', <ophyd_async.core._device.DeviceVector at 0x7eff30605790>),
#  ('lvdsin', <ophyd_async.core._device.DeviceVector at 0x7eff30606120>),
#  ('lvdsout', <ophyd_async.core._device.DeviceVector at 0x7eff306060c0>),
#  ('outenc', <ophyd_async.core._device.DeviceVector at 0x7eff30607da0>),
#  ('pgen', <ophyd_async.core._device.DeviceVector at 0x7eff30607b00>),
#  ('sfp3_evr', <ophyd_async.core._device.Device at 0x7eff306077d0>),
#  ('srgate', <ophyd_async.core._device.DeviceVector at 0x7eff30607530>),
#  ('system', <ophyd_async.core._device.Device at 0x7eff30607440>),
#  ('ttlin', <ophyd_async.core._device.DeviceVector at 0x7eff30604650>),
#  ('ttlout', <ophyd_async.core._device.DeviceVector at 0x7eff30637260>)]

# panda.pulse
# Out[34]: <ophyd_async.core._device.DeviceVector at 0x7eff12d94f50>

# list(panda.pulse.children)
# ---------------------------------------------------------------------------
# TypeError                                 Traceback (most recent call last)
# Cell In[35], line 1
# ----> 1 list(panda.pulse.children)

# TypeError: 'method' object is not iterable

# list(panda.pulse.children())
# Out[36]: 
# [('1', <ophyd_async.fastcs.panda._block.PulseBlock at 0x7eff30636ae0>),
#  ('2', <ophyd_async.fastcs.panda._block.PulseBlock at 0x7eff30636a50>),
#  ('3', <ophyd_async.fastcs.panda._block.PulseBlock at 0x7eff118964b0>),
#  ('4', <ophyd_async.fastcs.panda._block.PulseBlock at 0x7eff11895e50>)]

# list(panda.pulse[2])
# ---------------------------------------------------------------------------
# TypeError                                 Traceback (most recent call last)
# Cell In[37], line 1
# ----> 1 list(panda.pulse[2])

# TypeError: 'PulseBlock' object is not iterable

# list(panda.pulse[2].children())
# Out[38]: 
# [('enable', <ophyd_async.core._signal.SignalRW at 0x7eff11896360>),
#  ('delay', <ophyd_async.core._signal.SignalRW at 0x7eff11896390>),
#  ('pulses', <ophyd_async.core._signal.SignalRW at 0x7eff11896150>),
#  ('step', <ophyd_async.core._signal.SignalRW at 0x7eff11896000>),
#  ('width', <ophyd_async.core._signal.SignalRW at 0x7eff11895df0>),
#  ('delay_units', <ophyd_async.core._signal.SignalRW at 0x7eff119e1df0>),
#  ('dropped', <ophyd_async.core._signal.SignalR at 0x7eff119e1be0>),
#  ('enable_delay', <ophyd_async.core._signal.SignalRW at 0x7eff119e1b80>),
#  ('label', <ophyd_async.core._signal.SignalRW at 0x7eff119e1ac0>),
#  ('out', <ophyd_async.core._signal.SignalR at 0x7eff119e18b0>),
#  ('queued', <ophyd_async.core._signal.SignalR at 0x7eff119e1910>),
#  ('step_units', <ophyd_async.core._signal.SignalRW at 0x7eff119e1820>),
#  ('trig', <ophyd_async.core._signal.SignalRW at 0x7eff119e1700>),
#  ('trig_delay', <ophyd_async.core._signal.SignalRW at 0x7eff119e1670>),
#  ('trig_edge', <ophyd_async.core._signal.SignalRW at 0x7eff119e1520>),
#  ('width_units', <ophyd_async.core._signal.SignalRW at 0x7eff119e1550>)]

# panda.pulse[2].pulses
# Out[39]: <ophyd_async.core._signal.SignalRW at 0x7eff11896150>

# rd(panda.pulse[2].pulses)
# Out[40]: <bluesky.utils.Plan at 0x7eff3018d660>

# RE(rd(panda.pulse[2].pulses))
# Out[41]: ()

# %runfile /nsls2/users/asligar/hex/hex-ob/real_demo/panda_demo.py --wdir

# RE(rd(panda.pulse[2].pulses))
# Out[43]: RunEngineResult(run_start_uids=(), plan_result=50, exit_status='success', interrupted=False, reason='', exception=None)

# %runfile /nsls2/users/asligar/hex/hex-ob/real_demo/panda_demo.py --wdir

# RE(my_plan())
# 50
# Out[45]: RunEngineResult(run_start_uids=(), plan_result=None, exit_status='success', interrupted=False, reason='', exception=None)

# %runfile /nsls2/users/asligar/hex/hex-ob/real_demo/panda_demo.py --wdir

# RE(my_plan())
# 50
# Out[47]: RunEngineResult(run_start_uids=(), plan_result='Hello AJ', exit_status='success', interrupted=False, reason='', exception=None)

# panda.pulse[2].pulses.get_value()
# Out[48]: <coroutine object SignalR.get_value at 0x7eff311f7740>

# await panda.pulse[2].pulses.get_value()
# Out[49]: 50

# import asyncio

# asyncio.run(panda.pulse[2].pulses.get_value())
# ---------------------------------------------------------------------------
# RuntimeError                              Traceback (most recent call last)
# Cell In[51], line 1
# ----> 1 asyncio.run(panda.pulse[2].pulses.get_value())

# File ~/hex/hex-ob/.pixi/envs/default/lib/python3.12/asyncio/runners.py:191, in run(main, debug, loop_factory)
#     161 """Execute the coroutine and return the result.
#     162 
#     163 This function runs the passed coroutine, taking care of
#    (...)    187     asyncio.run(main())
#     188 """
#     189 if events._get_running_loop() is not None:
#     190     # fail fast with short traceback
# --> 191     raise RuntimeError(
#     192         "asyncio.run() cannot be called from a running event loop")
#     194 with Runner(debug=debug, loop_factory=loop_factory) as runner:
#     195     return runner.run(main)

# RuntimeError: asyncio.run() cannot be called from a running event loop

# %runfile /nsls2/users/asligar/hex/hex-ob/real_demo/panda_demo.py --wdir

# %runfile /nsls2/users/asligar/hex/hex-ob/real_demo/panda_demo.py --wdir

# RE(move_panda(5))
# Out[54]: RunEngineResult(run_start_uids=(), plan_result=None, exit_status='success', interrupted=False, reason='', exception=None)

# %runfile /nsls2/users/asligar/hex/hex-ob/real_demo/panda_demo.py --wdir

# panda.pulse[2].step
# Out[56]: <ophyd_async.core._signal.SignalRW at 0x7eff123ba870>

# RE(mvr(panda.pulse[2].step, 1))
# Out[57]: RunEngineResult(run_start_uids=(), plan_result=(<AsyncStatus, device: panda-pulse-2-step, task: <coroutine object AsyncStatusBase.__init__.<locals>.wait_with_error_message at 0x7eff105dd210>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

# RE(mvr(panda.pulse[2].step, -1))
# Out[58]: RunEngineResult(run_start_uids=(), plan_result=(<AsyncStatus, device: panda-pulse-2-step, task: <coroutine object AsyncStatusBase.__init__.<locals>.wait_with_error_message at 0x7eff105dd6c0>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

# RE(mvr(panda.pulse[2].step, 10))
# Out[59]: RunEngineResult(run_start_uids=(), plan_result=(<AsyncStatus, device: panda-pulse-2-step, task: <coroutine object AsyncStatusBase.__init__.<locals>.wait_with_error_message at 0x7eff105ddb70>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

# RE(mvr(panda.pulse[2].step, -5))

# Out[60]: RunEngineResult(run_start_uids=(), plan_result=(<AsyncStatus, device: panda-pulse-2-step, task: <coroutine object AsyncStatusBase.__init__.<locals>.wait_with_error_message at 0x7eff105de020>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

# RE(mv(panda.pulse[2].step, 1))
# Out[61]: RunEngineResult(run_start_uids=(), plan_result=(<AsyncStatus, device: panda-pulse-2-step, task: <coroutine object AsyncStatusBase.__init__.<locals>.wait_with_error_message at 0x7eff105dcc70>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

# RE(mvr(panda.pulse[2].step, -5))
# Out[62]: RunEngineResult(run_start_uids=(), plan_result=(<AsyncStatus, device: panda-pulse-2-step, task: <coroutine object AsyncStatusBase.__init__.<locals>.wait_with_error_message at 0x7eff105de4d0>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

# RE(mv(panda.pulse[2].step, 1))
# Out[63]: RunEngineResult(run_start_uids=(), plan_result=(<AsyncStatus, device: panda-pulse-2-step, task: <coroutine object AsyncStatusBase.__init__.<locals>.wait_with_error_message at 0x7eff105dd300>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

# RE(mvr(panda.pulse[2].step, -5))
# Out[64]: RunEngineResult(run_start_uids=(), plan_result=(<AsyncStatus, device: panda-pulse-2-step, task: <coroutine object AsyncStatusBase.__init__.<locals>.wait_with_error_message at 0x7eff105dea70>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

# RE(mv(panda.pulse[2].step, 1))
# Out[65]: RunEngineResult(run_start_uids=(), plan_result=(<AsyncStatus, device: panda-pulse-2-step, task: <coroutine object AsyncStatusBase.__init__.<locals>.wait_with_error_message at 0x7eff105de5c0>, done>,), exit_status='success', interrupted=False, reason='', exception=None)
