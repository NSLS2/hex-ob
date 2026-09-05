"""Typed shutter PVs for the HEX sim (front-end shutter and photon shutter).

The blackhole fabricates ``...Pos-Sts`` as a float and ``...Cmd:Opn-Cmd`` as a string, which
hextools' ophyd-async ``Shutter`` (bool status, numeric command) refuses to connect to. These
records have the real types and behave: writing 1 to the open/close command flips the status.

PV names follow the beamline: ``<prefix>Pos-Sts`` (bi: Not Open/Open), ``<prefix>Cmd:Opn-Cmd``,
``<prefix>Cmd:Cls-Cmd`` (bo, momentary) and ``<prefix>Sts:OpnCmd-Sts`` (the profile's
front-end shutter status; 1 = open command in effect).
"""

from caproto import ChannelType
from caproto.server import PVGroup, pvproperty

SHUTTER_PREFIXES = {
    # front-end shutter: open by default so plans that check it can run
    "XF:27IDA-PPS{Sh:FE}": True,
    # photon shutter: closed by default; plans open it
    "XF:27IDA-PPS{L1-S1}": False,
}


class ShutterSim(PVGroup):
    pos_sts = pvproperty(
        name="Pos-Sts", value="Not Open", enum_strings=["Not Open", "Open"], dtype=ChannelType.ENUM,
        record="bi", doc="shutter position status",
    )
    opn_cmd_sts = pvproperty(name="Sts:OpnCmd-Sts", value=0, dtype=int, doc="open command in effect")
    open_cmd = pvproperty(name="Cmd:Opn-Cmd", value=0, dtype=int, doc="write 1 to open")
    close_cmd = pvproperty(name="Cmd:Cls-Cmd", value=0, dtype=int, doc="write 1 to close")

    def __init__(self, prefix: str, *, initially_open: bool = False, **kwargs):
        # caproto expands {macros} in prefixes; the beamline's braces are literal.
        super().__init__(prefix=prefix.replace("{", "{{").replace("}", "}}"), **kwargs)
        self._initially_open = initially_open

    @pos_sts.startup
    async def pos_sts(self, instance, async_lib):
        if self._initially_open:
            await instance.write("Open")
            await self.opn_cmd_sts.write(1)

    @open_cmd.putter
    async def open_cmd(self, instance, value):
        if value:
            await self.pos_sts.write("Open")
            await self.opn_cmd_sts.write(1)
        return 0  # momentary command

    @close_cmd.putter
    async def close_cmd(self, instance, value):
        if value:
            await self.pos_sts.write("Not Open")
            await self.opn_cmd_sts.write(0)
        return 0


def build_shutter_pvdb() -> dict:
    pvdb: dict = {}
    for prefix, initially_open in SHUTTER_PREFIXES.items():
        pvdb.update(ShutterSim(prefix, initially_open=initially_open).pvdb)
    return pvdb
