# Simulated Phantom — real ADPhantom IOC + fake camera (scaffold)

The Phantom tier of the simulated HEX beamline, per the accepted
architecture decision (2026-08-11): run the **real deployed ADPhantom
module** with the camera faked at the **wire-protocol level** — the same
pattern as the PandA tier (real engine + protocol sim), and the only shape
that honestly serves the digital-twin goal: all 8,328 live records and the
unmodified ADPhantom Phoebus screens work against the sim.

Two pieces:

- **`sim_camera.py`** — the fake camera: a loopback TCP pair (CTRL `:7115`,
  DATA `:7116`) speaking the PH16 command surface the deployed driver uses.
  Python-3 port of Diamond's `sim/SimServer.py` (shipped unmodified in the
  deployed module), extended with the fork's surface: `set`, dotted-path
  gets, `defc`/`auto`/`irig`/`meta` structs, 63 cine structs, the
  WTR→TRG→ACT→STR cine state machine, and `img {cine,start,cnt,fmt}`
  downloads. Reply framing matches the *fork's* parser (`Ok!` / `ERR:`,
  newline-terminated — the ancestor sim's bare `OK` would not work).
  Protocol-level tests: `tests/phantom_simcam_mock_test.py` (runs in the
  mock-tier CI).
- **The IOC** (next step) — the deployed `adphantom_329598e` module run via
  the `nsls2.ioc_deploy` adphantom role against
  [`hexsim-phantom1.yml`](hexsim-phantom1.yml) (the live `phantom-det1.yml`
  with `CAMERA_IP: 127.0.0.1`), following the kinetix build path:
  deploy in the `nsls2_ioc_deploy_el8` container, `docker commit` as
  `hexsim-phantom-ioc:local`, CA bound loopback-only on the dedicated port
  **:5105** (kinetix :5085, panda-ioc :5095, motor :5075).

## Ground truth this scaffold is built on (no guessed semantics)

| Fact | Source |
|---|---|
| Reply framing `Ok!` / `ERR:`, `\n`-terminated both ways | `ADPhantom.h:58-59`, `ADPhantom.cpp:1234` (deployed source, rsynced from xf27id1-det1) |
| Command verbs + struct/param paths | grep of `ADPhantom.cpp` (`get/set/rec/trig/attach/img/ximg/time/setrtc/rel/del`) |
| Struct reply format (tab dict, `\`-CRLF continuations) | ancestor `sim/SimServer.py` (byte-identical in the deployed module) |
| `ArrayCounter_RBV = lastfr+1` = post-trigger count during recording | `ADPhantom.cpp` status poll (~line 1370) |
| Cine state tokens WTR/TRG/ACT/STR | `ADPhantom.cpp` `checkState` calls |
| `NUM_CINES: 63`, prefix, camera IP/ports | live `phantom-det1.yml` + `records.dbl` snapshot |

## Honest TODOs (marked in `sim_camera.py`)

- **TODO(format)** — dotted-path *get* reply framing not yet verified
  against the driver's parser (struct gets are).
- **TODO(data)** — `img` streams correctly *sized* zero-frames, not the
  real fmt-token pixel packing `readoutDataStream` parses. The IOC-tier
  bring-up (driver actually connected) drives this out.
- **TODO(timing)** — `trig` completes the post-trigger phase instantly;
  real cameras pace at the programmed rate.

## Open beamline-side questions (AJ recon)

- **Trigger wiring**: which PandA output reaches the Phantom's FSYNC input
  vs its event-trigger input, and whether the train start is the event
  trigger on real hardware (assumed by `plans/phantom/tomo_scan.py`).
- **Time-series PandA design**: the legacy helpers drive `PULSE2` (scan
  train) gated by `BITS:A` — capture that design's block wiring from the
  PandA GUI (the way `Tomo_radio_1` was captured for the kinetix tier), so
  the sim design and `time_series_scan` can be built against it.

## Run (camera sim only, until the IOC lands)

```bash
hex-simulated-beamline/.toolenv/bin/python \
    hex-simulated-beamline/iocs/phantom/sim_camera.py   # 7115/7116 loopback
```
