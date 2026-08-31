# Kinetix ophyd-async device, from scratch

Hands-on tutorial (AJ + Nghia): build the ophyd-async areaDetector device for the
Kinetix from the ground up — driver IO, trigger logic, detector class — then compare
against upstream `ophyd_async.epics.adkinetix` at the end and decide keep-or-retire.

Lives under `tutorial/`, not `lib/`, on purpose: `lib/` converges on hextools, and this
is teaching material that must be free to differ from (or disagree with) upstream
without touching production paths. hextools keeps consuming upstream's
`KinetixDetector` regardless of the outcome here.

Verified first at the mock tier, then against the simulated HEX beamline's Kinetix
tier (`XF:27ID1-BI{Kinetix-Det:1}`, boot per `QUICKSTART.md`), then at the beamline.

Contents (written one step at a time):

- `kinetix.py` — `KinetixTriggerMode` / `KinetixReadoutMode` enums, `KinetixDriverIO`
  (step 1), `KinetixTriggerLogic` (step 2), `KinetixDetector` (step 3)
- tests land in `tests/` at repo root (step 4)
