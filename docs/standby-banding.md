# ES07D03: gradient banding on one unit after resume from standby

**Status:** observed once, recovered by monitor power-cycle. Root cause unconfirmed.
**Date:** 2026-10-29
**Suspected component:** scaler firmware (standby/resume path)

## Summary

After the host resumed from standby, one of two identical ES07D03 units (DP-10) showed strong colour banding on smooth gradients. The other unit (DP-12) on the same dock and MST link was unaffected. A host reboot did not clear the fault. A power-cycle of the affected monitor did.

## Setup

| Item | Value |
|---|---|
| Host | ASUS Zephyrus G16 GA605KM, AMD Radeon 860M (DCN 3.5), Arch Linux, KDE Plasma 6.8 (Wayland) |
| Dock | Lenovo ThinkPad USB4 Dock 5000, DisplayPort MST |
| Monitors | 2 × ES07D03, same firmware build (fill in: `ddcutil getvcp C9`) |
| Mode (both) | 3840×2160 @ 143.98 Hz, 8 bpc (automatic), RGB, HDR off, WCG off, no ICC profile |
| Link | 4 lanes HBR3 (0x1e), FEC active, DSC active on both streams |
| DDC/CI | KWin brightness control via DDC/CI (65 %) through the `i2c-vl822` bridge |

## Symptom

- Smooth gradients were posterized into visible steps. Overlapping blurred shapes showed hard contour edges.
- The banding was visible on every blurred surface: Plasma Login Manager, Plasma panel/popup blur, and Spotify's CSS `backdrop-filter` blur. Spotify's blur is rendered by Chromium, not KWin, so the cause was not a KWin effect.
- Only DP-10 was affected; DP-12 looked normal at the same time.

## Timeline

1. Host resumed from standby. The banding was present on DP-10 from then on.
2. A host reboot via the power button did not fix it. The monitor was not power-cycled; its standby/input-detect parts presumably stayed powered.
3. A Plasma 6.8.1 → 6.8.2 update was installed after the onset, so it is not the cause.
4. Power-cycling only the DP-10 monitor fixed it.

## Host-side evidence (captured while faulty)

From `amdgpu_dm_dtn_log`:

- **Colour pipeline:** all pipes had IGAM, DGAM, RGAM and gamut remap in bypass, and no 3D LUT or shaper. The GPU applied no colour transform to either output.
- **ODM:** each 4K stream used 2 pipes at 1920×2160.
- **DSC:** both streams were compressed, with different targets:

  | Output | Bytes_pp (1/16 bpp) | Effective |
  |---|---|---|
  | DP-12 | 151 | 9.44 bpp |
  | DP-10 | 146 | 9.125 bpp |

- **Underflow:** sticky flags were set on OTG1 and HUBP0/2. These are probably left over from mode set and are not considered causal.

Other observations:

- **No DP-10 debugfs entry:** DP-10 had no directory under `/sys/kernel/debug/dri/*/`, while DP-12 did. This suggests the MST connector was recreated on resume and its debugfs registration failed.
- **KScreen settings identical:** both outputs reported the same settings in `kscreen-doctor -o`.

## Interpretation

Confidence: moderate.

- **Host rendering ruled out.** Both outputs had identical, bypassed colour pipelines, and the symptom affected content from several independent renderers.
- **DSC difference too small.** A ~3 % lower DSC rate is unlikely to produce posterization on its own; DSC errors normally appear in fine detail, not as contour steps.
- **Persistence pattern points to the monitor.** The fault survived a host reboot and cleared with a monitor power-cycle. This points to state held in the monitor that is set wrongly on resume.
- **Candidates on the monitor side:**
  - Output dithering or FRC to the panel not re-enabled.
  - Wrong panel/output bit depth.
  - A gamma/LUT path left in a reduced-precision mode.
  - DSC decoder misconfiguration after resume.

**Not verified.** None of these tests were run before recovery:

- Screenshot test (did a host screenshot also band?).
- Cable/port swap between the two monitors.
- `ddcutil getvcp ALL` diff between the two units.

A host or dock contribution is therefore not fully excluded.

## Relation to known firmware bugs

This is the same area as the existing standby defects:

- Backlight stays faintly on in standby.
- Slow wake from standby.
- Power LED flips colour while in standby.
- USB hub is reset when the scaler enters or leaves standby.

The resume path does not seem to re-initialise all display state consistently.

## If it happens again: capture before recovering

1. **Screenshot test:** take a screenshot of a banded gradient and view it on the unaffected monitor. If it looks smooth there, the fault is downstream of the compositor (link, scaler or panel).
2. **Compare monitor state:**
   ```
   ddcutil detect
   ddcutil --bus <DP-10 bus> getvcp ALL > es07_bad.txt
   ddcutil --bus <DP-12 bus> getvcp ALL > es07_good.txt
   diff es07_bad.txt es07_good.txt
   ```
3. **Host pipe state:**
   ```
   sudo cat /sys/kernel/debug/dri/1/amdgpu_dm_dtn_log > dtn_bad.txt
   ```
   Note the DSC `Bytes_pp` per stream.
4. **Swap test:** swap the DP cables between the two monitors at the dock. If the banding follows the monitor, the fault is monitor-side. If it follows the port, it is host or dock.
5. **Scaler readback:** if `diag-poke` is flashed, dump the scaler register pages on the faulty unit and on the good unit with `tools/regdump.sh` and diff them (see `docs/diag-poke.md`).
6. **Recover:** power-cycle the affected monitor and record whether that alone fixes it.

## Leads for firmware analysis

- Trace the scaler's standby → resume path. Check which output-processing blocks are re-initialised: dithering/FRC to the eDP panel, output bit depth, gamma/LUT, and the DSC decoder.
- Compare the resume path against the cold-boot init path. The fault clears on power-cycle, so cold boot evidently initialises something that resume skips or initialises differently.
