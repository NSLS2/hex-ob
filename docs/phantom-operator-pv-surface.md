# Phantom operator PV surface — from the HEX Phoebus screens

Recon for the simulated beamline's Phantom tier: the PVs the **operator**
actually drives, extracted from the ADPhantom Phoebus screen set that HEX's
CS-Studio launcher opens for `XF:27ID1-ES{Phantom-Det:1}cam1:`.

- Source: `cs-studio-xf/ADet/phoebus/ADPhantom/*.bob` (macros from
  `cs-studio-xf/27id/main.bob`, read 2026-08-11).
- Extraction: `grep -h -o "<pv_name>[^<]*</pv_name>" *.bob` per file,
  deduplicated, cine indices collapsed to `C<n>:`.
- `$(P)$(R)` = `XF:27ID1-ES{Phantom-Det:1}` + `cam1:` at HEX.

This is the *operator* surface. The *plan* surface (what
`plans/phantom/` + `lib/phantom.py` drive) is a subset; a digital-twin sim
must serve both — which is the strongest argument for running the real
ADPhantom IOC against a fake camera rather than spoofing PVs: the screens
then work against the sim unmodified.

## Findings that were NOT in the ophyd device or the pyepics scripts

- **Per-cine state words**: every cine partition has its own
  `C<n>:State_RBV`; the overview screen polls bits B0/B1/B4/B8/B9 for up
  to **63 cines**, the details screen all of B0–B9. (The ophyd device only
  reads the camera-level `State_RBV` bits B0–B3, B9.)
- **`TotalFrameCount_RBV` ≠ `ArrayCounter_RBV`** — both exist and both are
  displayed. The legacy scripts wait on TotalFrameCount for post-trigger
  frames; the ophyd device waits on ArrayCounter. Which counts what is a
  driver-semantics question for the ADPhantom source.
- **Auto-trigger block**: `AutoTriggerMode/X/Y/W/H/Area/Thresh/Interval` —
  image-based (motion-detect) event triggering, operator-configurable.
- **Connection management**: `CONNECT` / `CONNECTED_RBV` — operators can
  drop and re-establish the camera link; a fake camera must survive it.
- **Cine-range download** (`DownloadStartCine`/`EndCine`, frame mode,
  speed, `AbortDownload`, `MarkCineSaved`) and a **guarded delete /
  repartition workflow** (dedicated confirm dialog — repartitioning is
  destructive).

## PVs by screen

### phantomTop.bob (main control)
AutoAdvance(+RBV) · AutoBref(+RBV) · AutoRestart(+RBV) · CineName(+RBV) ·
CONNECT · CONNECTED_RBV · CSRCount_RBV · MaxFrameCount_RBV · PerformCSR ·
PostTrigFrames(+RBV) · Preview(+RBV) · SelectedCine(+RBV) ·
SendSoftwareTrigger

### phantomBase.bob (ADBase area)
Acquire · AcqNotify · AcquireTime/AcquirePeriod(+RBV, .DISA gating) ·
ArrayCounter_RBV · ArraySize[_X_Y]_RBV · Bin/Min/Size/Reverse X/Y (+RBV,
.DISA) · ColorMode · DataType · DetectorState_RBV · Gain(+RBV) ·
Manufacturer/Model_RBV · MaxSizeX/Y_RBV · PortName_RBV ·
State_RBV.B1/.B2/.B3 · StatusMessage_RBV · TotalFrameCount_RBV

### phantomDetails.bob (advanced)
AutoRestart/AutoSave(+RBV) · AutoTrigger{Mode,X,Y,W,H,Area,Thresh,
Interval}(+RBV) · Aux1/2/4PinMode(+RBV) · CameraTemp/SensorTemp/FanPower/
ThermoPower_RBV · EDR(+RBV) · ExtSyncType(+RBV) · FrameDelay(+RBV) ·
QuietFan(+RBV) · ReadySignal(+RBV) · SettingsSave/Load/Slot(+RBV) ·
SyncClock · TriggerEdge(+RBV) · TriggerFilter(+RBV)

### phantomCine.bob (partition overview)
CineCount_RBV · C\<n\>:State_RBV.B0/.B1/.B4/.B8/.B9 (n = 1..63)

### phantomCineDetails.bob (one partition)
C\<n\>:{FirstFrame,LastFrame,FrameCount,Width,Height,Name}_RBV ·
C\<n\>:State_RBV.B0–B9 · Download · AbortDownload · DownloadCount_RBV ·
DownloadStart/EndFrame(+RBV) · DownloadSpeed · DroppedPackets_RBV ·
SelectPixelDataFormat

### phantomDownload.bob
Download · AbortDownload · DownloadCount_RBV ·
DownloadStart/EndFrame(+RBV) · DownloadStart/EndCine(+RBV) ·
DownloadFrameMode · DownloadSpeed · DroppedPackets_RBV ·
FrameReadSpeed_RBV · MarkCineSaved · SelectPixelDataFormat ·
StatusMessage_RBV

### phantomDelete.bob
Delete · DeleteStart/EndCine(+RBV) · StatusMessage_RBV

### phantomPartitionConfirm.bob
CineCount_RBV · PartitionCines
