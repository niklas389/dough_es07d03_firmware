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
| `diag-poke` (`9e14e7a`) | not kept | `9e14e7a` | as v2 | v3 + RAM page `0x2039xx` (the `diag-log` data) | as v3; the RAM page is read with a plain byte load |
| `diag-poke` (previous) | not kept | `2a8d8e2` | as v2 | v3 + RAM `0x2022xx`–`0x2024xx` and `0x2039xx` | as v3; RAM `0x20xxxx` read with a plain byte load; allowlist tables in the image head (`0x201F00`) |
| `diag-poke` (current) | `patches/diag-poke.json` | see git log | as v2 | previous + RAM `0x453Cxx` (wake event `0x453C74`, wake port `0x453C78` reported by the PM51) | as previous; RAM `0x20xxxx`/`0x45xxxx` read with a plain byte load |

Wake source after a deep-standby wake (current version): `tools/poke.sh read
0x453C74` gives the PM51 wake event (2 = port activity, `0x0A` = port
message), `tools/poke.sh read 0x453C78` the port the PM51 reported (2–5; 5 also
means "no unsuppressed port matched"). Both are 0 after a mains start
(`docs/firmware-map.md` §21).

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
`diag-poke` of 2026-10-07 or later) keeps a RAM log of the **first 64** events
with a millisecond time stamp, for the timing of a start or a deep-standby
wake:

- milestones: `I` main init start, `D` init done (EEPROM, scaler), `X`
  front-end set-up done (`sub_261FA8`), `R` boot panel preparation returned,
  `M` main loop start, `B` backlight on (with the caller of `sub_245919`;
  `0x23AED9` = relight on valid video);
- `Q` every mailbox command (cmd, sub, first data byte) until the backlight is on;
- `P` port state changes (`sub_22F2C7`), `W` changes of the watched bytes
  (port 0/1 status `+0x20`, port 1 flags `+0x1C`, OSD state, `panel-prepower`
  state), checked every main-loop pass;
- `N`/`F` panel on/off with caller, `S` OSD timer end, `E` state 4 ("No
  signal") entry, `G` standby gate result.

Since 2026-10-07 code and data are in the zero areas of the uncompressed image
head (code `0x201400`, data `0x202200`: ms counter, event count, 64 × 8-byte
entries), which the boot loader copies to RAM with the head and which no
firmware code uses. So `diag-log` no longer shares the `0x203800` padding with
the regular patches and can be built with the whole list. `diag-poke` reads
`0x2022xx`–`0x2024xx` as RAM; its allowlist tables moved to `0x201F00`.
`tools/logread.py` reads only the entries in use (about 2 DDC transactions per
byte). The log starts empty at every firmware start; a deep-standby wake clears it.

The time base starts when the 1 ms timer runs, i.e. after the boot loader has
checked and unpacked the firmware. Stopwatch time to picture minus the `B`
time is therefore the time spent before the main firmware runs (standby
controller wake, boot loader, image unpacking).

| Patch name | File | Source (`tools/patches_src_diag_log.py` at) | Events |
|---|---|---|---|
| `diag-log-v1` | `patches/diag-log-v1.json` | `40e8def` | F, N, S, E, G |
| `diag-log` (`3e65d35`) | not kept (checkpoints after the eight calls between `D` and the panel prepower) | `3e65d35` | v1 + I, D, M, B, C |
| `diag-log` (`c5f9fd5`) | not kept | `c5f9fd5` | v1 + I, D, M, B, C (inside `sub_261FA8`), Q ≥ 20 ms |
| `diag-log` (`d9e1508`) | not kept | `d9e1508` | v1 + I, D, M, B, Q ≥ 100 ms, P, Y |
| `diag-log` (`bdbf388`) | not kept | `bdbf388` | v1 + I, D, M, B, P, W (main-loop variable watcher) |
| `diag-log` (`c55fd42`) | not kept | `c55fd42` | v1 + M, B, P, Q (all mailbox commands 2.1–4.0 s; 1.5–4.5 s in `91d16fc`) |
| `diag-log` (`9e14e7a`) | not kept | `9e14e7a` | v1 + M, B, Q (payload of the first configuration update after the main-loop start) |
| `diag-log` (current) | `patches/diag-log.json` | see git log | v1 + I, D, X, R, M, B, Q (all commands until the backlight), P, W; 64 entries; image head area |
| `diag-log-mb` | `patches/diag-log-mb.json` | see git log (`MODE=mb`) | v1 + I, D, X, R, M, B, P, Q (every transaction with its duration, whole run); last 64 entries; no W |
