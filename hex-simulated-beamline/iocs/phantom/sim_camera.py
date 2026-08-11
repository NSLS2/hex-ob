#!/usr/bin/env python3
"""Phantom camera protocol simulator — the fake camera behind the REAL
ADPhantom IOC in the simulated HEX beamline (dec: real-IOC + ported
SimServer, 2026-08-11).

Python-3 port of Diamond's miroCamera ``sim/SimServer.py`` (byte-identical
copy ships in the deployed adphantom_329598e module), extended for the
deployed fork's protocol surface. Sources of truth, in order:

- the deployed driver source (``~/git_projects/ADPhantom-deployed``,
  ADPhantomApp/src/ADPhantom.cpp) — command verbs, reply framing
  (newline-terminated both ways, success sentinel ``Ok!``, error prefix
  ``ERR:`` — the ancestor sim's bare ``OK`` would NOT satisfy this driver);
- the live record snapshot (``~/git_projects/phantom-det1-ioc-snapshot``,
  records.dbl, NUM_CINES=63);
- the ancestor sim server (struct-reply format: ``\\t``-indented dict with
  backslash-CRLF line continuations).

Protocol surface the fork's driver uses (recon 2026-08-11):
  get <struct>       struct in {cam, info, defc, auto, irig, meta, c0, c<n>}
  get <a.b[.c]>      dotted single-parameter read   [reply format UNVERIFIED]
  set <a.b> <value>  parameter write
  rec <n>            start recording into cine n (0 = default/current)
  trig               software event trigger
  attach {port:N}    attach the data-stream connection
  img {cine:N, start:S, cnt:C, fmt:TOK}   download frames to the data port
  ximg / time / setrtc / rel <n> / del    acknowledged, minimally modeled

Cine state machine (tokens the driver parses from ``c<n>.state``):
  WTR (waiting for trigger) -> TRG (triggered) -> ACT (active)
  -> STR (stored).  During recording the driver derives:
    ArrayCounter_RBV      = lastfr + 1  (post-trigger frames; 0 pre-trigger)
    TotalFrameCount_RBV   = frcount     (pre+post total)

TODO markers below are honest gaps, not oversights — each needs either the
driver run against this server (the IOC-tier bring-up) or a wire capture
from the real camera:
  - TODO(format): dotted-path get reply framing.
  - TODO(data): real download stream layout (readoutDataStream expects
    per-frame headers + pixels in the fmt token's packing; we send sized
    zero-frames as a placeholder).
  - TODO(timing): recording advances instantly on trig; real cameras pace
    at the programmed rate.

Only ever bind loopback: this is a stand-in for hardware, never a service.
"""

import argparse
import copy
import fcntl
import re
import signal
import socketserver
import sys
import threading
import time

OK = "Ok!"          # PHANTOM_OK_STRING (ADPhantom.h:58)
ERR = "ERR:"        # PHANTOM_ERROR_STRING (ADPhantom.h:59)


# --------------------------------------------------------------------------
# Parameter structures. cam/info bases carried over from the ancestor sim
# (a Miro M310 identity); defc/auto/irig/meta added for the fork's driver,
# keyed off the parameter paths ADPhantom.cpp reads/writes. Cine structs
# (c0 = "current", c1..cN) are generated from CINE_TEMPLATE.
# --------------------------------------------------------------------------

CAM = {
    "syncimg": 0, "master": 0, "tcmode": 0, "trigpol": 1, "trigfilt": 1,
    "frdelay": 0, "startonacq": 1, "aux1mode": 0, "aux2mode": 0,
    "aux4mode": 0, "memgateen": 1, "rtoen": 0, "membpp": 12, "tsformat": 1,
    "longready": 0, "dark": 0, "quiet": 0, "tsetsns": 30, "tsetcam": 50,
    "cines": 63, "timezone": -3600, "lang": "en_US",
}

INFO = {
    "hwver": 8001, "pver": 16, "sver": 1023, "fver": 39,
    "model": "Phantom T2410 (sim)", "sensor": 62, "serial": 17277,
    "memsz": 12288, "maxcines": 64, "name": "hexsim-phantom",
    "xmax": 1280, "ymax": 800, "xinc": 64, "yinc": 8,
    "minfrate": 24, "maxrate": 1000000, "expdead": 427, "minexp": 1000,
    "cinemem": 12181, "snstemp": 30, "tepower": 54, "camtemp": 52,
    "fanpower": 28,
    "features": "bref blk4 burst edr attach earlyimg notify atrig aexp cf quiet shtr",
    "imgformats": "8 8R P16 P16R P10 P12L",
    "setup": "hexsim",
}

# Default-cine settings: what "set defc.*" writes and "get defc" reads.
DEFC = {
    "res": "1280 x 800", "rate": 1000.0, "exp": 5000, "edrexp": 0,
    "ptframes": 100, "frcount": 12181, "shoff": 0, "hqenable": 0,
    "decimation": 1, "format": 0,
}

AUTO = {
    "acqrestart": 0, "bref": 0, "filesave": 0,
    "trigger": {
        "mode": 0, "x": 0, "y": 0, "w": 0, "h": 0,
        "area": 0, "speed": 0, "threshold": 0, "interval": 0,
    },
}

IRIG = {"synced": 0, "offset": 0}

META = {"name": "", "comment": "", "lens": "", "fstop": 0, "flen": 0}

CINE_TEMPLATE = {
    "res": "1280 x 800", "rate": 1000.0, "exp": 5000, "edrexp": 0,
    "ptframes": 0, "frcount": 0, "state": "{ DEF }",
    "firstfr": 0, "lastfr": 0, "format": 0, "decimation": 1,
    "frsize": 40336,
    "trigtime": {"secs": 0, "frac": 0},
}


def dict_to_response(name, dict_in, level=None):
    """Ancestor sim's struct-reply serializer, kept byte-compatible:
    tab-indented ``key : value`` lines with backslash-CRLF continuations."""
    tabs = "\t" * (level or 0)
    reply = tabs + name + " : {\t\\\r\n"
    new_level = 1 if level is None else level + 1
    for item, value in dict_in.items():
        if isinstance(value, dict):
            reply += dict_to_response(item, value, new_level) + "\t\\\r\n"
        else:
            quote = '"' if isinstance(value, str) else ""
            reply += tabs + "\t" + item + " : " + quote + str(value) + quote + ",\t\\\r\n"
    reply += tabs + "}"
    return reply


class SimCamera:
    """The camera model: parameter store + cine state machine + data port."""

    def __init__(self, num_cines: int = 63):
        self.lock = threading.RLock()
        self.params = {
            "cam": dict(CAM, cines=num_cines),
            "info": dict(INFO),
            "defc": dict(DEFC),
            "auto": copy.deepcopy(AUTO),
            "irig": dict(IRIG),
            "meta": dict(META),
        }
        for i in range(0, num_cines + 1):  # c0 = current/default view
            self.params[f"c{i}"] = copy.deepcopy(CINE_TEMPLATE)
        self.recording_cine = None
        self.data_socket = None

    # -- parameter access ---------------------------------------------------

    def resolve(self, path):
        """Walk a dotted path to (container, leaf_key), or None."""
        parts = path.split(".")
        node = self.params
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        if not isinstance(node, dict) or parts[-1] not in node:
            return None
        return node, parts[-1]

    def get(self, name):
        with self.lock:
            if name in self.params:
                return dict_to_response(name, self.params[name])
            hit = self.resolve(name)
            if hit is None:
                return f"{ERR} Parameter {name} not known"
            node, key = hit
            value = node[key]
            quote = '"' if isinstance(value, str) else ""
            # TODO(format): single-parameter reply framing unverified against
            # the driver's parser — mirrors the struct line style for now.
            return f"{name} : {quote}{value}{quote}"

    def set(self, name, raw_value):
        with self.lock:
            hit = self.resolve(name)
            if hit is None:
                return f"{ERR} Parameter {name} not known"
            node, key = hit
            current = node[key]
            try:
                if isinstance(current, float):
                    node[key] = float(raw_value)
                elif isinstance(current, int):
                    node[key] = int(float(raw_value))
                else:
                    node[key] = raw_value.strip('"')
            except ValueError:
                return f"{ERR} Bad value for {name}: {raw_value}"
            return OK

    # -- cine state machine -------------------------------------------------

    def rec(self, cine: int):
        """Start recording into cine *cine* (0 = the default cine)."""
        with self.lock:
            name = f"c{cine}" if f"c{cine}" in self.params else "c1"
            c = self.params[name]
            c["ptframes"] = self.params["defc"]["ptframes"]
            c["rate"] = self.params["defc"]["rate"]
            c["exp"] = self.params["defc"]["exp"]
            # Pre-trigger: recording circulates, no post-trigger frames yet.
            c["state"] = "{ WTR ACT }"
            c["frcount"] = 0
            c["firstfr"] = 0
            c["lastfr"] = 0  # driver: lastfr+1 == post-trig count, 0 pre-trig
            self.recording_cine = name
            return OK

    def trig(self):
        """Software event trigger: complete the post-trigger phase.

        TODO(timing): instantaneous — the full post-trigger count lands at
        once. Real cameras record ptframes at the programmed rate first.
        """
        with self.lock:
            if self.recording_cine is None:
                return f"{ERR} Not recording"
            c = self.params[self.recording_cine]
            pt = int(c["ptframes"])
            c["state"] = "{ TRG STR }"
            c["trigtime"] = {"secs": int(time.time()), "frac": 0}
            c["firstfr"] = -max(0, int(c["frcount"]))
            c["lastfr"] = pt - 1
            c["frcount"] = int(c["frcount"]) + pt
            self.recording_cine = None
            return OK

    # -- data stream --------------------------------------------------------

    def img(self, spec: str):
        """Download request: stream frames to the attached data socket.

        TODO(data): placeholder payload — correctly SIZED zero-frames (the
        cine's frsize per frame), not the real fmt-token pixel packing that
        readoutDataStream parses. Enough for socket-level plumbing; the
        IOC-tier bring-up drives the real format work.
        """
        m = re.search(r"cine\s*:\s*(-?\d+).*?start\s*:\s*(-?\d+).*?cnt\s*:\s*(\d+)", spec)
        if not m or self.data_socket is None:
            return f"{ERR} img: no attach / bad spec {spec!r}"
        count = int(m.group(3))
        cine = int(m.group(1))
        name = f"c{max(cine, 0)}" if f"c{max(cine, 0)}" in self.params else "c1"
        frame = b"\x00" * int(self.params[name]["frsize"])
        sock = self.data_socket

        def pump():
            try:
                for _ in range(count):
                    sock.sendall(frame)
            except OSError:
                pass  # client went away mid-download; fine for a sim

        threading.Thread(target=pump, daemon=True).start()
        return OK


class CtrlHandler(socketserver.StreamRequestHandler):
    """One control connection (the driver holds it open)."""

    def handle(self):
        cam = self.server.cam
        while True:
            line = self.rfile.readline()
            if not line:
                return
            command = line.decode("ascii", "replace").strip()
            if not command:
                continue
            reply = self.dispatch(cam, command)
            if reply is None:
                return
            self.wfile.write((reply + "\n").encode("ascii"))

    def dispatch(self, cam, command):
        verb, _, rest = command.partition(" ")
        rest = rest.strip()
        if verb == "get":
            return cam.get(rest)
        if verb == "set":
            name, _, value = rest.partition(" ")
            return cam.set(name, value.strip())
        if verb == "rec":
            return cam.rec(int(rest or 0))
        if verb == "trig":
            return cam.trig()
        if verb == "attach":
            # attach {port:N} — the driver opened the data connection first;
            # we bound it in DataHandler, so just acknowledge.
            return OK if cam.data_socket is not None else f"{ERR} no data connection"
        if verb in ("img", "ximg"):
            return cam.img(rest)
        if verb in ("time", "setrtc", "rel", "del", "bref"):
            return OK  # acknowledged; no deeper model yet
        if verb == "exit":
            return None
        return f"{ERR} Unknown command {command!r}"


class DataHandler(socketserver.BaseRequestHandler):
    """The data-stream connection: registered, then written to by img()."""

    def handle(self):
        self.server.cam.data_socket = self.request
        # Hold the connection open until the peer closes it.
        while True:
            try:
                if not self.request.recv(1024):
                    break
            except OSError:
                break
        if self.server.cam.data_socket is self.request:
            self.server.cam.data_socket = None


class ReusableServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    cam: SimCamera  # attached after construction (shared by ctrl + data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (loopback only — never expose)")
    parser.add_argument("--ctrl-port", type=int, default=7115)
    parser.add_argument("--data-port", type=int, default=7116)
    parser.add_argument("--num-cines", type=int, default=63,
                        help="cine partitions (HEX deploys 63)")
    args = parser.parse_args(argv)

    if not args.host.startswith("127."):
        sys.exit("REFUSING to bind non-loopback: this fakes hardware.")

    # Single instance per port pair (armed_gate_bridge lesson: an orphaned
    # helper silently corrupts later runs). flock dies with the process.
    lock = open(f"/tmp/hexsim-phantom-cam-{args.ctrl_port}.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("ERROR: another sim_camera holds this port's lock — kill it first.")

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    cam = SimCamera(num_cines=args.num_cines)
    ctrl = ReusableServer((args.host, args.ctrl_port), CtrlHandler)
    data = ReusableServer((args.host, args.data_port), DataHandler)
    ctrl.cam = data.cam = cam

    threading.Thread(target=data.serve_forever, daemon=True).start()
    print(f"sim_camera up: ctrl {args.host}:{args.ctrl_port}, "
          f"data {args.host}:{args.data_port}, {args.num_cines} cines",
          flush=True)
    try:
        ctrl.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ctrl.shutdown()
        data.shutdown()


if __name__ == "__main__":
    main()
