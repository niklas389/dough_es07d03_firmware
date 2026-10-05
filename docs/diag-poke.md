# diag-poke: live register access over DDC/CI

Diagnostic patch for experiments on the running monitor. VCP `0xEA`/`0xEB`
set the register address (high/low 16 bits), VCP `0xEC` reads (GET) or writes
(SET, value ≤ `0xFF`) one byte. Tools: `tools/poke.sh` (single register),
`tools/regdump.sh` (ranges), `tools/watch.sh` (periodic power-state log),
`tools/glowtest.sh` (guided `0x434` test), `tools/logread.py` (reads the `diag-log` event log).

Not for daily use. Every write is volatile: a mains power cycle (≥ 10 s)
restores everything. No EEPROM, flash, PM51 code or factory data can be
reached.

## Versions

All versions use the same VCP codes and the same main code cave
(`0x203DC0`, address variable at `0x203FF4`). Build with exactly one of them.

| Patch name | File | Source (`tools/patches_src_diag_poke.py` at) | Writes allowed | Reads allowed | Read method |
|---|---|---|---|---|---|
| `diag-poke-v1` | `patches/diag-poke-v1.json` | `3137dee` | `0x422`, `0x426`, `0x428`, `0x43A`, `0x43B`, `0x44A`–`0x44D`, `0x2E902F4A`, `0x2E902F4B` | pages `0x03xx`, `0x04xx`, `0x101Exx`, scaler `0x102Fxx` (any sub-bank) | single read through the firmware helper `sub_23D972` |
| `diag-poke-v2` | `patches/diag-poke-v2.json` | `799f4fe` | v1 + `0x434`, `0x436` | as v1 | as v1 |
| `diag-poke-v3` | `patches/diag-poke-v3.json` | `1a9ebef` | as v2 | v1 + PM PWM `0x05xx`, PWM unit `0x103Cxx`/`0x103Dxx` | interrupts masked (SR IEE/TEE), three reads, `0xFFFE` (UNSTABLE) if they differ; extra code at `0x203C60` |
| `diag-poke` (current) | `patches/diag-poke.json` | see git log | as v2 | v3 + RAM page `0x2039xx` (the `diag-log` data) | as v3; the RAM page is read with a plain byte load |

Return values of a GET on `0xEC`: `0x00`–`0xFF` value, `0xFFFF` address not
readable (BLOCKED), `0xFFFE` three reads differed (UNSTABLE, current version
only).

Writes to PM pin registers (`0x4xx`) go through `reg_write_mask`
(`0x23DADB`, PM51 register lock) as two masked writes: set the 1 bits, then
clear the 0 bits. Scaler registers are written with `sub_23D9E7`.

## Known effects (hardware tests 2026-10-04)

| Write | Effect |
|---|---|
| `0x426` bit 6 = 0 | backlight enable off; the LEDs still glow faintly (LED supply stays on) |
| `0x2E902F4B` | brightness value; `0x00` = minimum brightness, not off; no effect on the glow |
| `0x44A` bits 7/6/2/1 | no visible effect |
| `0x44B` bit 3 = 0 | **LED supply off**: backlight fully dark, CPU/DDC/DP link keep running. Setting it again needs a vendor panel-off/on with video before the backlight works (see `bl-supply-off`) |
| `0x434` bit 7 = 0 | **main power off**: CPU stops, mains power cycle needed |
| `0x434` bit 6 = 0 | **main power off** (immediately): CPU stops, mains power cycle needed |
| `0x434` bit 4 | panel supply (VLCD) |

## Known limits

- Versions v1/v2: scaler sub-bank reads can return another sub-bank's
  register when an interrupt switches the sub-bank between select and read.
  Fixed in the current version.
- While the firmware is busy (key presses, OSD, panel sequences) many DDC
  transfers fail; `regdump.sh` prints `ERR` for those. Repeat the read.

## diag-log (event log)

`patches/diag-log.json` (source `tools/patches_src_diag_log.py`, requires
`diag-poke`) keeps a RAM log of the last 16 events with a millisecond time
stamp: panel off (`sub_245860`, only when the panel is actually on) and panel on (`sub_245919`) with their callers,
the OSD timer expiry handler (`sub_258AB1`: re-enters "No signal", ends the
logo or a popup), the OSD state-4 entry handler
(`sub_26A7C5`, arms the 255 s countdown), the standby gate result in the
power-save entry (`0x2613A0`) and the start-up milestones: main init start
(`I`), init done after EEPROM and scaler/receiver set-up (`D`), main loop
start (`M`), backlight on (`B`, with the caller of `sub_245919`;
`0x23AED9` = relight on valid video) and a checkpoint after each of the eight
calls between `D` and the panel prepower (`C done sub_…`). A 1 ms ISR hook keeps the time base. Data:
`0x203968` (ms), `0x20396C` (event count), `0x203970` (ring, 8 bytes per
entry). Read with `tools/logread.py`. The log starts empty at every firmware
start; a deep-standby wake clears it.

The time base starts when the 1 ms timer runs, i.e. after the boot loader has
checked and unpacked the firmware. Stopwatch time to picture minus the `B`
time is therefore the time spent before the main firmware runs (standby
controller wake, boot loader, image unpacking).

| Patch name | File | Source (`tools/patches_src_diag_log.py` at) | Events |
|---|---|---|---|
| `diag-log-v1` | `patches/diag-log-v1.json` | `40e8def` | F, N, S, E, G |
| `diag-log` (current) | `patches/diag-log.json` | see git log | v1 + I, D, M, B, C |
