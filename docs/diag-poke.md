# diag-poke: live register access over DDC/CI

Diagnostic patch for experiments on the running monitor. VCP `0xEA`/`0xEB`
set the register address (high/low 16 bits), VCP `0xEC` reads (GET) or writes
(SET, value ≤ `0xFF`) one byte. Tools: `tools/poke.sh` (single register),
`tools/regdump.sh` (ranges), `tools/glowtest.sh` (guided `0x434` test).

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
| `diag-poke` (current) | `patches/diag-poke.json` | `1a9ebef` | as v2 | v1 + PM PWM `0x05xx`, PWM unit `0x103Cxx`/`0x103Dxx` | interrupts masked (SR IEE/TEE), three reads, `0xFFFE` (UNSTABLE) if they differ; extra code at `0x203C60` |

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
