# ES07D03 firmware map — `Beta03 (rev1169-E771)`

Package: `ES07D03_Beta03_rev1169-E771_USB_update.bin`, 1,344,628 bytes,
sha256 `d9be1e1c7aad81813faa7490a200fe6cfb83d0f371169f4ff94b829ea64c5ce3`.
Flashed at SPI `0x400000` (FW2); all offsets below are package offsets unless
marked as runtime addresses.

Everything here was derived from the package itself by static analysis.
"Confirmed" means read and checked in the code or verified by computation.
Anything else is marked as an inference.

## 1. Package layout

| Offset | Size | Content |
|---|---|---|
| `0x000000` | `0x0F00` | 8051 boot stub (`clr EA` …) then AEON R2 exception vectors at `0x100`, `0x200`… |
| `0x002000` | | sboot stage 1 (R2, base 0). Image CRC check, BL/pad init, BDMA copy of stage 2, banner strings `MST9U: … Oct 30 2020` |
| `0x00714D` | `0x4EB8` | sboot stage 2, copied to DRAM `0x1000000` (entry `0x1000100`). Header parsing, main-image CRC, zlib inflate, jump to `0x200100` |
| `0x005D00` | | zlib/inflate strings, USB update strings (`updated file in USB is found`) |
| `0x00FF00` | `0x100` | Chip info block: `MST9U4`, `BGA`, `D32133e`, `BUS`, `Oct 30 2020 16:14:45`, `MSVC0000S3`, `SBT_YYMMDD00536735000` |
| `0x010000` | `0x80` | **Image header** (see §2) |
| `0x010080` | ≈`0x9E80` | **PM51** 8051 firmware, executed from flash. sboot writes `base+0x10080` to the PM51 code-base registers (`0xA00021EC/F0`) |
| `0x020080` | ≈`0xAB80` | Second 8051 image (same vector layout as PM51; role not yet analysed) |
| `0x030080` | `0x3800` | **Main firmware head**, uncompressed: R2 vectors (reset at `+0x100`), startup, `+0x1100` magic `0x55AA5678`, `+0x1147` `BE AD DE`, `+0x114A` main length (u32 LE), panel name `L-QMD55MWWAC-3333`, build `Jul 29 2024 11:34:08` at `0x31280` |
| `0x032080` | | `TEL\tX3i` key-blob table: entries `id(2) offset(4,BE) size(4,BE) flag(1)` |
| `0x033880` | `0xF148B` | **Main firmware body**, raw deflate (wbits −15) → `0x250678` bytes |
| `0x124D0B` | 6 | u32 LE inflated size `0x250678`, then `BE 15` (not checked by the loader) |
| `0x124D18` | | TEL entry `0x0109` (size `0x20008`) starts here, mostly zero |
| `0x125D00` | `0x13C00` | **SECU_R2** HDCP co-processor firmware (uncompressed, `Mar 23 2020`) |
| `0x144D20`–`0x148468` | | TEL entries `0x0110/0111/0112/0120/0121/0122/0817/0827` (encrypted HDCP 1.x / 2.x key material) |
| `0x148468` | 8 | TEL entry `0xD000`: `55 AA AB CD 00 00 BB B7` |
| `0x148470` | 4 | Package CRC (big-endian) |

The extra region at SPI `0x550000`–`0x5F9244` mentioned in the tools README is
**not** part of this package; it is the tail of a larger (V108/106) package.

## 2. Image header (`0x10000`, u32 little-endian)

| Field | Value | Meaning |
|---|---|---|
| `+0x00` | `0x30080` | main image start |
| `+0x04` | `0x200000` | DRAM load address |
| `+0x08` | `0x2F4C91` | load end (`+0x04` + main length) |
| `+0x0C` | `0x124D11` | main image end |
| `+0x14` | `0x94CD4117` | CRC of `[+0x00, +0x0C)` |
| `+0x18`, `+0x1C` | 0 | alternate-image pointer (unused here) |
| `+0x20` | `0x148470` | package length without trailing CRC |
| `+0x24` | `0x10000` | header offset |
| `+0x60` | `0x18071D0B` | build stamp (yy=0x18, mm=7, dd=0x1D, hh=0x0B → 2024-07-29 11h) |
| `+0x64` | `0x400000` | SPI base of this image |

## 3. Integrity checks (both confirmed by computation)

Both use the MST9U BDMA CRC engine: **CRC-32, polynomial `0x04C11DB7`,
MSB-first (not reflected), init 0, no final XOR**.

1. **Package CRC** (sboot stage 1, `0x2000`): over `[0, 0x148474)` including
   the trailer must give 0. Equivalently, the CRC of `[0, 0x148470)` is
   stored big-endian at `0x148470`. On failure FW2 is skipped and the factory
   image at SPI `0` boots (`CRC32 of dual image merge.bin FAIL`).
2. **Main CRC** (sboot stage 2): CRC of `[0x30080, 0x124D11)` must equal
   header `+0x14`.

The 2 bytes after the inflated-size field are not covered by any check
beyond the main CRC. `tools/es07fw.py` recomputes everything.

## 4. Boot chain

1. 8051 stub at `0x0` → R2 reset `0x100` → stage 1 `0x222D`: chip/DDR banner,
   PM status, `sub_2000` package CRC (sets `*(0xB0000AE8)` = image base
   `0x400000` or 0), BDMA copies stage 2 to `0x1000100`, jumps.
2. Stage 2 `0x100035E`: reads the header at `base+0x10000`, checks head magic
   `BE AD DE`, BDMA-CRCs the main image, copies the `0x3800`-byte head to
   `0x200000`, copies the deflate stream to `0x1100000`, inflates to
   `0x203800` (size from the stream trailer), jumps to `0x200100`.
3. Head startup `0x200100`: cache init, BSS clear `0x453E80`–`0x48E280`,
   stack `0xB0000FFC`, jump to C entry `0x26F528`.

## 5. Main firmware runtime image (base `0x200000`)

Built with `es07fw.py unpack`: head (`0x3800`) + inflated body.

| Range | Content |
|---|---|
| `0x200000`–`0x2ADCC6` | code (2,753 functions found; 199k instructions; 38 indirect jumps unresolved) |
| `0x2ADCC6`–`0x453E78` | switch tables, rodata (MCCS capabilities string at `0x3CB1C8`, PQ tables), initialised data |
| `0x453E80`–`0x48E280` | BSS |
| `0x4824D0` | settings RAM image (EEPROM mirror), pointer at `0x3B5F38` |
| `0x486500` | settings shadow (last value read from/written to EEPROM) |
| `0x47EB40` | DDC/CI rx/tx buffers, `0x80` per port |
| `0x3B4950` | per-input-port table, `0xB0` bytes per entry |

Conventions (from the vendor gcc ABI): `r1` stack, `r9` link, args `r3..r8`,
return `r3`, data little-endian, instructions big-endian and 2/3/4 bytes long.

**Address note.** The other analysis session placed the inflated body at
`0x300000` instead of `0x203800`. Its addresses are this map's runtime
address **+ 0xFC800** (e.g. its `0x35DB21` = `0x261321` here). The link
address `0x203800` is confirmed by 205 movhi/ori string references that land
exactly on string starts.

## 6. Subsystems located

### DDC/CI — `ddc_process_command` `0x26AD19`
Opcode in `buf[1]`, VCP code in `buf[2]`, value in `buf[3..4]`. Handled opcodes:
`01` Get VCP, `03` Set VCP, `07` timing, `0C` save, `F3` capabilities, and
vendor `B1 C0 C6 C8 CC D0 F0 F1 F5`. Get-VCP dispatch starts at `0x26AFCD`,
Set-VCP dispatch at `0x26B1E7`. Called from `ddc_poll` `0x20CF68`, which sets
settings `+0x4C` bit 5 for the duration of the call.

### VCP D6 (power mode), set path at `0x26CA9F`
| Value | Action |
|---|---|
| `05` | `power_soft_off` `0x26A632`: clears `+0x48` bit 0 (power on) and saves `+0x48..+0x49` to the EEPROM → stays off across AC cycles; power button needed |
| `01` while off | injects power key `0x2A` into `key_process` |
| `02`–`04` while on | if not already in power-save: `0x4551AC` \|= 2 (standby request) **and settings `+0x4C` \|= 0x10** |
| `01` while on | if in power-save (`0x4551AC` bit 0): sets active port re-detect flag |

The `+0x4C` bit 4 is read only at `0x258F78` (key handler): with the bit set,
keys < 5 trigger an input re-detect instead of opening the OSD. It is cleared
only by `settings_monitor_defaults` `0x262388` (runs on a blank/version-changed
EEPROM, i.e. the "Processing update" stage). Settings `+0x48..+0xD1` are
saved as one block (`nvram_save_monitor`), so the bit persists. See
`patches/d6-standby-lock.json`, `patches/osd-lock-ignore.json`.

### Settings / NVRAM
External **I²C EEPROM**, device address `0xA0`, bit-banged; write-protect via
pad registers `0x42C`/`0x42E`. Range-based API: `nvram_save_range(off,len)`
`0x245B6C`, `nvram_load_range(off,len)` `0x245A35`.

| EEPROM range | Block |
|---|---|
| `0x000`–`0x047` | system (byte 0 = layout version `0xB8`, `+0x46` = `0x55AA`) |
| `0x048`–`0x0D1` | monitor settings (`+0x48` power flags, `+0x4C` runtime/lock flags, `+0xC4` defaults-valid magic `0xC1`; `+0x5A` is likely the active input, inferred) |
| `0x0D2`–`0x5F1` | colour/user settings |
| `0x632`–`0x7A8` | tail blocks |
| `0x1794`–`0x1C2F` | **factory data** (EEPROM base `0x1000` from `0x340000`): records of `0x16` B at `0x1794`, `0x3CA` B at `0x17C0` (XOR checksum in the last 2 bytes), `0x2C` B at `0x1B8A`, 8 B at `0x1BB6`, `0x50` B at `0x1BDF`. Loaded by `0x204352`–`0x205B5A`; a checksum failure loads defaults into RAM only (`sub_2040D6`). Written only by the vendor factory DDC/CI commands (`sub_26DE36` → `sub_205BDC`/`sub_204851`). The settings defaults loader never touches it. |

`nvram_init` `0x2636B0`: if the first 16 bytes are `0xFF`, write magic and
defaults. If byte 0 ≠ `0xB8`, load defaults for all blocks. If `+0xC4` ≠
`0xC1`, reload the monitor-settings defaults.

**Consequence:** reflashing SPI never resets settings. Only the version-change
update stage (or a blank EEPROM) does.

### Power / standby
- `power_key_state_task` `0x258E5D` (state byte `0x457854`; `0x45792D` is likely a pending-key/countdown byte, inferred)
- `power_event` `0x2612F5`: power on/off sequences, driving pads `0x43A/0x43B`
  (inferred: panel/backlight enables) and `0x44A–0x44D`, `0x422`
- `standby_gate_query` `0x2612F9`: refuses power-save when the active port
  has flags `0x20000|0x20` and the mailbox query answers 0 (query via `mailbox_query` `0x238FA5`; the other session places its registers in bank `0x1033`, not re-checked here) → the no-signal
  countdown loops forever (LED white/red cycling). See
  `patches/standby-gate.json`.

### Other identified pieces
- HDCP 1.x/2.x handler and mailbox to SECU_R2 (strings at `0x2AE518`…)
- PQ / XC (scaler) code, HDR panel handling (strings around `0x33C900`)
- Panel: `MST9U4_PanelLM270WR8_eDP_9U4`

## 7. Not yet analysed
- PM51 (`0x10080`) and the second 8051 image (`0x20080`): needed for the
  standby backlight glow if real power-save does not remove it.
- The 38 unresolved indirect jumps and the co-processor query semantics.

## 8. Standby loop (no-signal → power-save)

All addresses are runtime addresses. Variables are as exposed by `patches/diag-probes.json`.

**Countdown** (`sub_261C04`, tick at `0x261CCB`, runs while `0x4551A2` ≠ 0)
- `cnt` (`0x4551A6`) counts down unless `0x453C70` bit 15 is set.
- At 250 it sets `flg` (`0x4551AE`) bit 4, the pre-standby state with the red LED (`sub_26693C`).
- At 0 it sets `pwr` (`0x4551AC`) bit 1, "power-save requested", and clears `flg` bit 4.

**Entry** (`sub_26136B`, reached through the thunk at `0x261496`, called every main-loop pass)
- Nothing happens unless `pwr` bit 1 is set.
- It then calls `standby_gate_query` (`0x2612F9`).
- **Refused** (returns 1):
  - clears bit 1, sets `rws` (`0x4551CC`) = 1 and the 5-tick re-query timer `0x4551CD`;
  - panel off (`sub_245860`); the CPU keeps running.
- **Allowed:**
  - clears bit 1; if the power flag (settings `+0x48` bit 0) is set, sets `pwr` bit 0;
  - `sub_245787`, LED (`sub_261910(0)`), panel off (`sub_245860`);
  - fills the PM wake block at `0x48A740`: port mask, LED colours from settings `+0xBB..+0xC2`;
  - `sys` (`0x455164`) = 1.
- The main loop then runs `sub_23D6AA`:
  - copies `sys` into the block;
  - drives the power pads `0x43A/0x43B`, `0x44A–0x44D`, `0x422`;
  - `sub_20C537`, `sub_23EF7E(1)`;
  - **parks the AEON CPU** in an endless loop at `0x20E5B5`.
- Leaving real power-save therefore restarts the main firmware. At boot, `sub_2414AE` reads PM register `0x3AA`; bits 3:2 = `0b10` set `pwr` bit 7.

**Gate** (`standby_gate_query`)
- It only applies when the active port's flags (`0x3B4950 + n*0xB0`, u32 `+4`) have `0x20000` and `0x20` set.
- It then sends two mailbox requests to the DP-receiver co-processor (registers `0x1033C0`–`0x1033C9`):
  1. `(0x30, 0xFF, 7)` maps the port to a receiver ID;
  2. `(0x60, 0xFF, 0x0B)` returns a state byte.
- A state byte of 0 refuses power-save. What that byte represents is not known.

**After a refusal** (stock): `sub_23ADAF` (`0x23AEB8`) turns the panel back on (`sub_245919`) and clears `rws` when the DP port reports a link event (port byte `+0x1C` bit 1). The no-signal cycle restarts, giving the white/red LED loop roughly every 4.3 minutes.

**Hardware result with `standby-gate`** (2026-10-02 log)
- At `cnt` 1 → 0 the probes stop answering for about one sample.
- The next sample shows exactly the boot values written by `sub_23FF28`: `cnt`=0, `pnl`=0, `off`=0, `sys`=0, `pwr`=0x14.
- Then the no-signal cycle starts again.
- So power-save was entered and left within seconds, followed by a firmware restart.
- `pwr` bit 7 stayed clear, so the restart was not reported by PM register `0x3AA` as a normal PM wake (value `0b10`). PM wake with another code, and watchdog reset, are both still possible.
- Conclusion: the vendor gate keeps the monitor out of power-save while the DP side is still active, and forcing entry only moves the loop.

**Kernel log during the same test**
- At 13:28:49, the moment power-save was entered, the monitor's hub (`2109:2822`/`2109:8886`) disconnected.
- In the same second amdgpu logged about 27 `DMUB HPD RX IRQ` (DP IRQ_HPD) events through the dock.
- The hub came back at 13:28:52, i.e. the monitor had already woken.
- Reading: entering power-save disturbs the DP link, the dock and GPU respond with link/AUX traffic, and that traffic wakes the monitor.
- The owner reports clean standby only when the laptop is disconnected from the dock and the dock itself sleeps, so nobody answers.

**State table** `0x3BAAFC`, `0x1C` bytes per state, indexed by `0x457854`
- `+0x08`: key-map table pointer.
- `+0x10`: entry handler.
- State 3 entry `sub_26A7A9` arms `cnt` = 5.
- State 4 entry `sub_26A7C5` ("No signal") arms `cnt` = 255; if `flg` bit 0 is set, `cnt` = 1.
- Re-entering state 4 is what restarts the countdown after a refusal.

## 9. Power paths (panel, backlight, standby hand-off)

Panel: LG LM270WR8-SSA1, eDP 4×4 lanes. It has **no backlight driver of its own**; the LED driver is on the monitor mainboard.

Datasheet power sequence (spec 3-6, table 3-7) against the firmware:

| Timing | Limit | Firmware | Status |
|---|---|---|---|
| T1 VLCD rise | 0.5–10 ms | board power switch | not firmware |
| T2/T3 sink ready, HPD | 10–200 ms / 15–200 ms after VLCD | 25 ms, eDP TX on, then per eDP port `sub_21177B` polls a status bit (very likely HPD, `sub_218B75`) every 10 ms, up to 20 times = 200 ms, before training | ok; on timeout it continues without training (fault case only) |
| T4–T6 link training → valid video | T6 ≤ 100 ms | `sub_2117E1` training, then video | not measurable from code |
| T8 valid video → LED on | ≥ 350 ms | 550 ms in `sub_245919` | ok; **violated by `sub_2457FB`** (no link at all) → `standby-lhs` |
| T9 LED off → VLCD off | ≥ 200 ms | 320 + 80 + 20 ms | ok |
| T10 video end → VLCD off | 0–500 ms | ≈ 100 ms in `sub_245860` | ok; **`sub_24578B` leaves the link on with VLCD off** → `standby-lhs` |
| T12 VLCD off time | ≥ 1000 ms | timer armed, never checked | **violated** → `panel-t12` |

Notes 3 (pull VLCD down when the interface is invalid) and 4 (LED supply off
whenever VLCD changes) are met by `sub_245860`/`sub_245919`. Note 1 also asks
for the full sequence on mode changes; whether the scaler keeps the panel link
running (black video) or cycles the panel on input timing changes has not been
checked.

**Pins** (main firmware, written via `reg_write_mask(reg, value, bitmask)` `0x23DADB`, RIU byte registers; a pin uses an output register and an output-enable register, 0 = driven)

| Output / enable | Bit | Role (from usage) |
|---|---|---|
| `0x426` / `0x428` | 6 | backlight enable (mirrored in `bl` `0x453BF3`) |
| `0x434` / `0x436` | 4 | panel VLCD |
| `0x434` / `0x436` | 6 | driven high by the main firmware at boot (`0x241349`), driven low by the PM51 on standby entry (`0x53B2`). Clearing it in link-held standby stopped the CPU at once (no DDC reply to the write; hardware test 2026-10-04). Not usable in link-held standby |
| `0x434` / `0x436` | 7 | PM51 only: set high and released when awake, driven low on standby entry (`0x4C26`). **Main power:** clearing `0x434` bit 7 in link-held standby (`0x436` bit 7 still 1) stopped the CPU within ~0.1 s; keys and DDC dead until a mains power cycle (hardware test 2026-10-04). Not usable in link-held standby |
| `0x43A` / `0x43B` | 1 | set by real power-save and by the power-on path |
| `0x44A` / `0x44C` | 7, 6, 2, 1 | cleared on real power-save (`sub_23D6AA`), set again by `power_event` |
| `0x44B` / `0x44D` | 3 | set by `power_event` at AC power-on (`0x260F67`) and by the PM51 on wake (`0x403C`); cleared on deep standby / power-off (`0x23D72F`, `0x261062`). **Backlight supply:** clearing it with the monitor on turns the backlight fully off, glow included, while CPU, DDC and the DP link keep running. Setting it again did not bring the backlight back (enable toggled too); a vendor panel-on did (link-held standby, bit set again, then wake). Hardware tests 2026-10-04; used by `bl-supply-off` |
| `0x422` | 3, 2 | set on power-save; software I²C bus lines (`sub_240866`), i.e. bus idle, not a supply |
| `0x42C` / `0x42E` | | EEPROM write protect |

Boot pin setup is `sub_2411B5` (called from `sub_2414AE`).

**Backlight brightness:** `sub_23A17E` → `sub_26159A` maps 0–100 to 0–255 (piecewise linear, brightness 50 at settings `+0x34`) and writes it to scaler register `0x2E902F4B` (sub-bank `0x2E`, bank `0x102F`, reg `0x4B`; address form: top byte = sub-bank, bit 23 = sub-bank access). That sub-bank also holds video-processing registers, so whether `0x4B` is the physical backlight PWM is **not verified**; at brightness 0 the backlight still lights. Panel-off never changes it; it only drops the enable pin `0x426` bit 6, which is also its state at boot.

**Backlight glow (open):** the LED strings (16 × 4 packages, 22.9 V at 75 mA per panel datasheet) are fed by a CN5120 boost whose input reaches the strings through the inductor and diode when it is shut down; each string returns through its own MOSFET (`BQ*`). In link-held standby only the enable pin is low and the glow can persist; in deep standby (`sub_23D6AA`: `0x44A` bits 7/6/2/1 cleared, `0x422` bits 3/2 set, clocks stopped) it ends. `patches/diag-poke.json` + `tools/poke.sh` allow testing these outputs one at a time during the glow.

**Sequences** (`sub_241505(ms)` is a busy-wait on a 1 ms ISR counter)

| Routine | Sequence | Assessment |
|---|---|---|
| `sub_245919` panel on (guard `pnl`=0) | `sub_23CCD5(2)`, VLCD on, 25 ms, eDP on `sub_21D167(1)`, 10 ms, `sub_211741`+`sub_2117E1` (link), 550 ms, `pnl`=1, `sub_23CCD5(0)`, backlight on; if a re-detect is pending (port `+0x1C` bit 0, and `0x453C70` bit 3 clear) → panel off instead | meets T2/T8 |
| `sub_245860` panel off (guard `pnl`=1) | `pnl`=0, backlight off, 320 ms, `sub_2116F5`, `sub_23CCD5(1)`, 80 ms, `sub_23CCD5(0)`, eDP off `sub_21D167(0)`, 20 ms, VLCD off, arm 1200 ms timer (`0x4551B6`, `off`) | T9, T10 ok; **T12 timer never checked by anyone** (`panel-t12` adds the check at panel-on) |
| `sub_24578B` pre-standby off (no guard) | as above but no `pnl` change, no eDP off, no timer | **called every main-loop pass during pre-standby** (≈420 ms blocking each); eDP TX stays on with VLCD off |
| `sub_2457FB` panel on without link | `sub_23CCD5(2)`, VLCD on, 25+550 ms, `sub_23CCD5(0)`, backlight on | **no eDP enable or link training** → backlight on without valid video (violates T8); used when pre-standby is cancelled (`0x259026`, `sub_266B56`) |

`sub_23CCD5(mode)` writes bits 5:4 of scaler sub-bank `0x10` reg `0x43` (window `0x102F`). Mode 2 is used during panel power-up, 0 for normal output, and 1 briefly during power-down. The exact meaning is not decoded.

**Standby hand-off**
- `sub_23D6AA` (sys 1/2): writes the PM mailbox block `0x48A740`, drives the power pins above, `sub_20C537`, `sub_23EF7E(1)`, then `0x20E56B`.
- `0x20E56B`: clock/IRQ shutdown (`0x2B08/0x2B18/0x2B28` = `0xFFFF`), then the handshake:
  - `sub_20E531` polls PM reg `0x10FC` up to 9 times;
  - if it gets no answer, `sub_20E379` writes `0x10F4`=1, `0x039D` bit 6, `0x0398`=`0x829F`, `0x038A` bit 6;
  - the CPU then parks.

**PM51** (`tools`: radare2 8051; image `pkg 0x10080`, code base 0)
- Register helpers: `0x2C75` masked write (addr R4..R7, value RAM `0x54`, mask `0x55`), `0x31A4` byte write (`0x5A`), `0x351E` 16-bit write, `0x2B6F` read.
- It writes PM regs `0x03A6` (mode bits), `0x03AA` (wake status), `0x038A`/`0x039D`, the mailbox bank `0x1033C0..C9`/`0x1033F1..F9`, and pins `0x0434`/`0x0436` bits 6/7.
- It never touches the backlight enable `0x426`/`0x428` or VLCD (`0x434` bit 4).
- On standby entry (`0x4BE9`) it drives `0x434` bits 6 and 7 low; on wake (`0x4002`) it releases them. These are the only supply-like outputs that change between link-held standby and deep standby, where the backlight glow ends. Both stop the main CPU when cleared in link-held standby (tested 2026-10-04; the monitor did not glow during either test, so their effect on the glow is unknown). No output reachable from the main firmware removes a supply in link-held standby without stopping the CPU.
- Its wake-source handling is the remaining open item for real standby.

## 10. PM51 standby controller (package `0x10080`, 8051, code base 0)

Disassembled with radare2 (`-a 8051`). Keil C51 style: XRAM variables at `0x5000–0x63xx`, and Keil runtime helpers such as `0x1E65` (load 32-bit constant from code).

**Main loop**
- `main` is `0x9562`: init (`0x90F5`, `0x9D88`, `0x9CCE`), set state awake (`0x9ACF`).
- It then loops at `0x9574`: `0x3EB4` (power state machine), `0x8AEB`, `0x9D3B` (event poll) → `0x880F`, `0x9CE1`, `0x9D02`, `0x9665`, `0x0019`.

**State**
- `0x5E6A`: 0 = awake, 1 = standby, 2 = power off.
  - Set by `0x9B30` (→1), `0x9C91` (→2) and `0x9ACF` (→0).
  - `0x96FB` copies it into PM reg `0x03AA` bits 4:2 (1 → code 1, 2 → code 3).
- `0x5E6B` is the sub-state for `0x3EB4`:
  - 0 (`0x3ED9`): enter standby;
  - 2 (`0x3FEC`): sleeping; calls `0x745A` and goes to sub-state 1 on a wake decision;
  - 1 (`0x4002`): wake. Re-drives pins `0x0434/0x0436` bits 6/7, `0x042E`, `0x044B`, `0x043A`, waits for PM reg `0x039C` (≤1000 ticks), writes the wake code and sets state 0;
  - 3 (`0x418E`): awake.

**Events** (`0x5BAA`, writes the event code to `0x5E89` and its parameter to `0x5E8A`)
- Snapshot: PM interrupt status `0x0385`, `0x0386`, `0x038B`, `0x03A2`, `0x03A3`, `0x0364` → XRAM `0x5001–0x5007`.

| Source | Event |
|---|---|
| `0x0365` low nibble | 4 (no wake) |
| keys (`0x6881`, debounced, `0x7847` reads key pins) | `0x0C` and up |
| `0x0386` bit 7: main-firmware mailbox (`0x3EC2..0x3EF3`) | 5/6/7 (command 4 → 5, 5 → 6 power off, else 7) |
| message channel `0x6E0A` (only if `0x5E6D` bit 1: `0x53EC` shifts right, then bit 0 is tested) | `0x0A` |
| port activity `0x7D10` | 2, port index in `0x5E8A` |
| software queue `0x61E9`, filled by the message dispatcher `0x5ED5` (jump table `0x5F35`) for serial frames with command `0xF0` from the front-end (`0x7EE5` → receive `0x565A` → `0x8A89`): message type 0 → event 9 (24-bit connector bit mask in `0x6208`, port via `0x69B3`); type 4 → events 5/6/7 | that value |
| `0x5E87` | 4 |

- Port activity is configured by the constant table at code `0x2928`, `0x23` bytes per port, 6 ports.
  - Byte +0 is the port type.
  - Bytes +1..+4 are a 32-bit config. Port wake is enabled when bit 3 of the last byte is set (ports 2–5).
  - Type 1 triggers on PM status `0x0386` bit 5; types 2, 3 and 4 on `0x038B` bits 0, 1 and 2 (mask table at code `0x291E`).
  - XRAM `0x5E81+port` ≠ 0 makes the finder skip a port; if no port matches, the finder returns port 5, and event 2 is raised anyway (§21).

**Wake decision** `0x745A` (after re-arming PM regs `0x03A6`/`0x03BC`)

| Event | Result |
|---|---|
| 1, 3, 9, `0x0A`, `0x0E` | wake |
| 2 | wake if `0x9D54` returns ≠0 |
| 4 | stay asleep |
| 5–7 | `0x90B6` (6 while in standby → power off) |
| `0x0C`, `0x0D`, `0x0F–0x15` | wake if state is 1 or 2 (`0x9CBA`) |

**`0x9D54` is a stub.** It loads 0/200/0 into scratch bytes `0x24–0x26` and returns 1 unconditionally. Any activity interrupt on an enabled port therefore wakes the chip, including the DP side-channel (AUX) traffic that the GPU/dock generates in response to the IRQ_HPD burst at standby entry (kernel log: ~27 `DMUB HPD RX IRQ` at the moment the hub dropped).

**Code banking.** The PM51 uses Keil code banking. `0x10080` is bank 0 and `0x20080` is bank 1 (previously listed as the "second 8051 image"). The common area `0x0000`–`~0x34FF` is identical in both, and IRAM `0x1F` (low 3 bits) selects the bank. Inter-bank calls go through the table at `0x28A0` (`mov dptr,#target; ajmp 0x2812`) and the switch routines at `0x2D00`. The wake decision `0x745A` and the stub `0x9D54` are bank-0 code. Bank 0 is free (`0xFF`) from `0x9D9A`.

**`pm51-wake-recheck`.** `0x9D54` jumps to new bank-0 code at `0xA000`. It waits 200 ms (`0x9D2D`), then re-reads the two conditions that raised event 2 in `0x5BAA` (PM `0x0386` bit 5, PM `0x038B` bits 2:0) and wakes only if one is still set. The PM51 only reads these registers and never writes them, so whether they latch is unknown; if they do, the behaviour is the same as stock.

## 11. Why the no-signal cycle restarts, and `standby-lhs`

- **Power/OSD state table** `0x3BAAFC` (`0x1C` per state; `+0x08` key map, `+0x10` entry handler, `+0x14` periodic handler):
  - 0 power off (`power_soft_off`);
  - 3 "cable not connected" (`cnt`=5);
  - 4 "No signal" (`cnt`=255);
  - 6 normal (no message);
  - 7 power-on logo (entry `sub_26A61C` = full panel-on, draw `sub_2599FC` loads palette/tiles; see §12);
  - 0x0E–0x18 OSD menus.
- **Signal events:** `sub_263995`. In state 4 or 6, a DP link event (port `+0x1C` bit 1) with port status `+0x20 & 0x28` clear sets `0x453C70` bit 14 and arms `0x4551B5`=2 (another path arms 10 with bit 15).
- When that timer expires, the countdown tick sets `0x453C70` bit 0. `power_key_state_task` then calls `sub_258AB1`, which re-enters state 4: "No signal", `cnt`=255, white LED.
- So link activity from a source that holds the link without video restarts the cycle.
- **Port status `+0x20` low nibble** (`sub_23A7CB`, from `sub_23A516`): values with bits 2–3 set mean no signal / unsupported. The vendor relight after a refusal (`0x23AEC3`) already requires a valid timing.
- **Input state machine** `sub_22F2C7`: per input path, state records at `0x47FA64 + n*0x7C`; state 2 → `sub_226F7A` (detect), states 4–5 → `sub_23ADAF`.

**`standby-lhs`** (source `tools/patches_src_standby_lhs.py`) turns the refusal into a stable link-held standby. This is the DP-conformant behaviour for a source that keeps the sink in D0 without video. Deep power-save follows as soon as the vendor's 5-tick gate re-query sees the link released. See `patches/standby-lhs.json` for the exact hooks.

**Countdown-end flash** (found with `diag-log`, 2026-10-05): in link-held standby the
255 s countdown keeps running. At `cnt` 0 the tick sets `pwr` bit 1 (power-save
requested) and clears the pre-standby flag in the same step. Before the power-save
entry asks the gate, the relight in `sub_23ADAF` (`0x23AED5`, our `cave_b`) saw no
pre-standby flag and switched the panel on; the refusal then switched it off again.
Result: a brief panel-on (and "No signal") every ~250 s. `cave_b` now also skips the
relight while `pwr` bit 1 is set.

## 12. Power-on logo and start-up

- **Tick:** the 1 ms ISR reloads `0x3B4948` with 1000 and sets `0x4551A2`
  each time it runs out, so the countdown task `sub_261C04` ticks once per
  second (`cnt`, the OSD timer `0x4551A4`, the re-evaluation timer `0x4551B5`).
- **Logo flag:** `0x453C70` bit 3. Only `power_event` sets it: AC power-on
  with the power flag set (`0x260F60`) and power-on events 6/0xE
  (`0x261007`). Wake from standby (event 7) clears it.
- **Boot:** `sub_261FDE` checks bit 3 and calls `sub_26A809`, which enters
  state 7: full panel-on with the logo. The state flags (+0x18 bit 6) make
  `sub_256B63` arm the OSD timer with 3 ticks, so the logo stays 2–3 s.
- **Logo end:** the timer expiry sets `0x453C70` bit 0, and
  `sub_258AB1` (`0x258AD2`) clears bits 0 and 3, sets bit 5, enters state 6,
  sets the active port's re-detect request (+0x1C bit 0) and marks it "no
  signal" (+0x20 |= 0x0C). Input detection therefore starts again after the
  logo, and `sub_245919` turns the panel off (re-detect pending, bit 3 clear)
  until the new mode is set. Power-on = logo time + panel off (+ T12) +
  detection + panel-on.
- **Brightness:** backlight brightness is per input, settings `+0x91 + port`
  (port index `0x47FAF5`), applied with the picture setup after detection.
  Why the logo appears dimmer was not traced; `no-logo` removes the phase.
- `patches/no-logo.json` stops both setters, so power-on takes the same path
  as a wake from standby.

## 13. Start-up order and timing notes

- `sub_261FDE`: pads, `nvram_init` (EEPROM, bit-banged I²C with ~4 µs
  half-periods, about 100 kHz; the 0x7A9-byte settings read takes roughly
  0.2 s), then `sub_23D3EB`.
  Halving the read half-period (`eeprom-fast-read`) breaks the start after a
  power-key off/on on hardware ("No signal", then standby), while a mains
  start works; the mechanism is not identified, so the stock timing stays.
- `sub_23D3EB`: `sub_2226F1` (scaler/receiver init, `power_event`), …, then
  `sub_20C6F3` → `sub_20C5EB`, which configures an external I²C device at
  `0x34` (the NAU8401 headphone DAC) with a fixed register table at
  `0x34220B` and blocks for 1 + 1 + 250 + 100 ms (datasheet anti-pop
  sequence). The same device is written again at standby entry (`sub_20C537`).
- The DP receiver's hot-plug control has not been located yet.
- `patches/panel-prepower.json` runs the vendor panel-on at `0x2620CC`
  (where the stock logo powered the panel) with the backlight held off and
  finishes it at the next panel-on call. v2 replaces the 550 ms busy-wait of
  that sequence with a countdown in slot 8 of the 1 ms ISR timer table
  (`sub_240C55`: 9 slots, active flags `0x455171`+n, halfword counters
  `0x45517A`+2n, cleared at 0; no vendor code uses them) and completes
  `pnl` = 1 / output mode 0 from the main loop (hook on the port-task call
  `0x262114`); see §17.

## 14. Board components (identified)

From the owner's board photos (`R01712273073` mainboard, PCB "Spectrum_D03 2021-05-08").

| Part | Marking | Role / notes |
|---|---|---|
| Scaler | MStar MST9U14RV4 (`MST9U4` in the package) | AEON R2 main CPU, PM51 8051 standby controller, SECU_R2 HDCP processor (package section `0109`) |
| Input front-end | MStar **MSB3300** | Between the HDMI/DP ports and the scaler. Very likely handles DP/HDMI reception (link training, hot-plug) itself, which would explain why no DP hot-plug control was found in the scaler code. V108's extra section `010F` ("HDMI/TMDS/DSC code") is probably its firmware (inference). |
| DRAM | 6× Winbond W632GU6NB | DDR3 |
| SPI flash | Winbond W25Q128JV (16 MB) | only the lower 8 MB used |
| Settings EEPROM | Fudan **FM24C128D** (16 KB) | I²C `0xA0`; user settings `0x000`–`0x7A9`, factory data `0x1794`–`0x1C2F`. Rated 1 MHz at 2.5–5.5 V, 400 kHz at 1.6 V; the firmware runs it at about 100 kHz. |
| USB hub | VIA VL822-Q7 + Winbond 25X20 (hub firmware flash, reading uncertain) | also the DDC/ISP bridge used for flashing |
| USB-PD | VIA VL103R-Q4 (PD controller), onsemi NCP81599 (buck-boost, I²C 0x74–0x77) | |
| USB-C / DP-alt | Diodes PI3DPX1207C (redriver), PI3USB31531 (crossbar, I²C 0x54–0x57 family), PI3USB32212 (USB switch) | |
| Headphone DAC | Nuvoton **NAU8401YG**, I²C `0x34` (fixed address `0011010`) | 7-bit register + 9-bit data. `sub_20C579` runs the datasheet's anti-pop power-up (R1 = `0x10F`, ~250 ms, table at `0x34220B`, 100 ms) at every start and wake; `sub_20C537` writes it at standby entry. Nothing else accesses it. `patches/audio-off.json` skips the power-up. |
| HDMI EDID EEPROMs | 2× AT24C02A (U14/U15, below the MSB3300) | 256 B each (inference: one per HDMI port) |
| Backlight LED driver | 2× 10-pin "AGQCZA" (+ "rNCVA" part next to each), not identified | boost stages with `B*` designators near connectors BJ1/BJ2 |

## 15. OSD popups (tile OSD)

- OSD states: table `0x3BAAFC` (`0x1C` per state). `+0x00`/`+0x01` window
  columns/rows in 12×18 px tiles (or a size function if `+0x18` bit 0),
  `+0x08` item page, `+0x0C` item count, `+0x10` entry handler, `+0x14`
  periodic handler. Popups: 2 power-on, 3 cable not connected, 4 No signal
  (25×3), 5 (25×3, two items), 8/9 input name (20×4), 0x0C (20×4), 0x19 (30×6).
- Item (`0x2C` bytes): `+0` column, `+1` row, `+4`/`+5` attribute
  (normal/selected), `+7` flags (bit 3: centred text), `+8` text function
  (returns a per-language descriptor: font slot, tile count, pixel width).
- Cell attribute byte: high nibble foreground, low nibble background
  (palette index); confirmed on hardware: colour 1 = see-through dark gray
  (header band), 15 = near-black (message area), 2 = white (text). Colour 0
  is used for unused menu areas and is assumed to be transparent. Messages are proportional text rendered into font RAM
  from slot `0x20` (`0x27C046`); characters are coded `A`=`0x20`, `a`=`0x3A`,
  space `0x0F`.
- Tile RAM access: `0x101C66` data port, `0x101C68` mode (1 code, 2
  attribute); window base/pitch at `0x101D10`/`0x101D12` + window × `0x20`.
  `sub_25C254` fills a rectangle, `sub_25C8F5`(col, row, code, count) a row.
- Custom glyphs (1 bpp, RLE words `count<<12 | 12-bit row`, `sub_27BC9C`):
  set `0x32591C` at code 0: 0 blank, 1 thin line, 2 lower half solid,
  3 arrow, 4 double line, 5 two lines, 6 block, 7 checker, 8 right edge;
  set `0x325C80` at `0xFE`: two half-circles. No corner glyphs.
- Frame (`sub_256C92` `0x256F88`): whole window attribute `0xFF` code 0
  (gray), then for popup states row 0 attribute `0x11` (dark band) and row 1
  glyph 2 in `0xF1` (dark→gray transition). Only state 0x19 places text in
  row 0; for all others the band stays empty. `patches/popup-flat.json`
  draws the one-line popups (2/4, 8/9/0x0C) entirely in colour 1 with white
  text (`0x21`) in the middle row; `patches/popup-round.json` loads four
  corner glyphs to codes `0x1C`–`0x1F` with the base set (`sub_253991`) and
  draws them with attribute `0x10`.
- Glyph code ranges: base set 0–8 and `0xFE`/`0xFF` (`sub_253991`), another
  set at 9–`0x18`, `0x2A`–`0x77` and three 96-glyph sets at 0 (`sub_2537EB`,
  overlay mode, reloaded with the base set afterwards), logo `0x4D`–`0xB0`,
  rendered popup text from `0x20`.

## 13. Other vendor packages (compared 2026-10-05)

Packages supplied by the owner (not committed):

| Package | Build | Notes |
|---|---|---|
| `BD_EVE_4K_Release_20220216_V106_rev988_USB update.bin` | Feb 16 2022 | same package layout, checksums OK |
| `ES07D03_V108_rev1148_USB update.bin` | Dec 19 2022 | last public release; version string `V108` |
| `ES07D03_Beta03_rev1169-E771_USB_update.bin` (base of this project) | Jul 29 2024 | version string `V108T` |
| `BD_EVE_4K_Release_20211126_V105_rev957_USB update.bin` | Nov 26 2021 | oldest public ES07D03 package; same layout, contains `010F` (MSB3300 firmware) like V106/V108 |
| `dough_es07e91_v1.0.19_USB-update.bin` (Spectrum Black, OLED) | 2025 | Realtek **RTD2739** scaler, panel LW315AQQ; different architecture, nothing transferable at code level |
| LG 28MQ780 `28MQ780_MSTAR_MST9W00V4_V3.3.0` (raw scaler flash image) | Mar 17 2022 | file name says MST9W00, but the code is the same MStar **MST9U** SDK (strings `./cpu/risc32/MST9U/interrupt.c`, `MST9U4_Panel…`; same AEON start-up). Image header at `0x11000`, runtime = `0x31080`–`0x3487F` + inflate of the deflate stream at `0x34880` (load `0x200000`, end `0x537940`, entry `0x271520`). Debug strings (`msAPI_*`, `MDrv_*`, `HDCPHandler_*`, EDID variant names, `HPD : %d`, `Check Signal : %d`). About 1600 of our 2753 functions have a counterpart; the input-port layer is the same code with other structure sizes; see §17 |

- PM51 standby controller, second 8051 image and `sboot` are byte-identical in
  V106, V108 and Beta03. Only the main runtime and `secu_r2` differ.
- V106 and V108 contain one panel-on and one panel-off routine (the
  equivalents of `sub_245919`/`sub_245860`). The pre-standby routines
  `sub_24578B` (panel off without `pnl`, called every main-loop pass) and
  `sub_2457FB` (panel on without link) exist **only in Beta03**. The
  pre-standby behaviour that `standby-lhs` reworks was therefore added in the
  beta.
- Vendor change logs: V104 "Reduced coil whine when used in HDR mode",
  "Less delay before image is displayed on PC"; V108 "Resolved an issue where
  the Windows desktop wallpaper disappeared after resuming from standby mode
  for some users with multiple monitors".

## 16. DisplayPort power management and link-held standby power

**What the DP standard requires of a sink** (VESA DisplayPort 1.1a §5.2.5 and
Appendix D; the same text is in DP 1.2 §5.1.5):
- The source puts the sink into power-save by writing `2` (D3) to DPCD `600h`
  and wakes it by writing `1` (D0). Other listed reasons for sink power-save:
  soft power button, source detected as absent.
- HPD must stay asserted unless the sink is powered off (an IRQ_HPD pulse or
  an intentional hot-plug event excepted), also in power-save.
- In power-save the AUX channel must be ready within 1 ms after differential
  activity is detected.
- "The Source Device may keep transmitting Idle Pattern over Main Link even
  when there is no stream to transmit … Therefore, the Sink Device must keep
  the Main Link receiver active as long as it is receiving either a stream or
  Idle Pattern and as long as it keeps the HPD signal asserted."

**Consequences for this monitor**
- The vendor gate (`standby_gate_query`, §8) refusing deep standby while the
  source holds the link is consistent with this, if its state byte means "D0
  with link active" (not decoded). A dock that removes the stream but keeps
  idle pattern and never writes D3 therefore keeps the monitor in link-held
  standby indefinitely (diag-log 2026-10-05: one refusal at the countdown end,
  then no allowed re-query in 710 s).
- Link-held standby itself is allowed: only the main-link receiver, AUX and
  HPD must stay active. Panel, backlight, audio and picture processing may be
  off. Measured 13 W there (deep standby 1.2 W).
- Deep standby must keep HPD asserted. Whether it does is not verified; the
  other monitor blanking twice during a wake suggests a hot-plug cycle.

**What deep standby switches that link-held standby does not** (`sub_23D6AA`
and the power-off path `0x261041`; power-on sets them again at `0x2611F4`)
- `0x44A`/`0x44C` bits 7, 6, 2, 1 (output/enable): driven low. Set high again
  at power-on in the order 7, 6, 2, 1 without delays. Function unknown
  (candidates: supplies or resets of the USB hub, the MSB3300, the audio path).
  The 2026-10-04 test showed no visible effect. In link-held standby
  (2026-10-06) `0x44A` = `0x00` and `0x44C` = `0xFF`: none of these pins is
  driven, so they are probably unused on this board (the power-on path that
  drives them, `0x2611F4`, runs only for event `0x11`). No power to gain there.
- `0x43A`/`0x43B` bit 1: set (1) in standby. On power-off it follows setting
  `+0xC3` (OSD value at `0x457857`, written by `sub_266C41`); meaning unknown.
- `sub_20B9A6(0)`: clears `0x407` bits 6:5 and writes `0x416` bits 7:4 via
  `sub_23DC0F`; meaning unknown.
- `sub_20C537`: `0x44B` bit 7 high, 100 ms, headphone DAC (I²C `0x34`) write.
- `sub_23EF7E(1)`: `sub_20EDCC(port, 1)` for each port with flags `& 0x0E`.
- `0x20E56B`: interrupts off, `0x2B08`/`0x2B18`/`0x2B28` = `0xFFFF` (likely
  clock gates), PM mailbox handshake; the PM51 then drives `0x434` bits 6/7
  low (main power).

**Start-up timing** (`diag-log`, power key from soft-off, 2026-10-06; ms since the 1 ms timer started):
I 0.112 s → D 0.893 s (EEPROM + scaler/receiver init) → panel prepower 5.506 s
(**4.6 s** in the calls between, static waits explain only ~0.5 s) → main loop
6.356 s → backlight on 10.235 s (relight on valid video, caller `0x23AED9`).
Checkpoints (second run): the 4.6 s are all in `sub_261FA8` (input set-up:
`sub_239BAE(0)`, then `sub_268877` → `sub_268668` / `sub_239223`). Those send
commands to the PM51 through `mailbox_query` (`0x238FA5`: wait until
`0x1033C0` is free, write the command, wait for the answer in `0x1033C1`, each
with a 10000-tick timeout at `0x4551C8`); no fixed delays. Working assumption,
not verified: the PM51 answers only after its own wake sequence.
Start type matters (2026-10-06): both 4.6 s runs were mains power-cut starts
(the PM51 boots from scratch); a power-key start (PM51 already running) had
no gap: sub_261FA8 done at 1.0 s, about 13 mailbox transactions of ~66 ms
each between 1.8 and 2.5 s, main loop 2.09 s, backlight 5.78 s.
Clock check (2026-10-06): 212.7 s wall time = 213.8 s log time, so the 1 ms
tick is accurate (within the ~1 s read-out uncertainty). The 11.0 s run was a
power-cut start; the 8.4 s stopwatch time belongs to a power-key start, whose
log shows the backlight at 5.8 s. So roughly 2.6 s pass between the power key
and the start of the log clock (PM51 wake, boot loader CRC and inflate),
assuming the stopwatch and log runs are comparable.

**Boot cost before the main firmware:** stage 2 of the boot loader CRCs the
main image and inflates 0xF148B bytes of deflate data to 0x250678 bytes
(§4). The 1 ms time base of `diag-log` starts only after that.

**Deep-standby wake, PC side** (`drm.debug=0x104` kernel log through the
Synaptics MST dock, 2026-10-06, aligned by command time and stopwatch;
firmware start ≈ command + 2.6 s):

| From command | PC / dock | Firmware clock |
|---|---|---|
| 0 – 1.3 s | stream to DP-17 allocated, mode set done | (deep standby) |
| +1.9 s | I²C over MST to the monitor | (PM51 wake) |
| +5.37 s | dock CSN: DP-17 **disconnected**, connector removed, desktop reconfigured | ≈ 2.75 s |
| +5.59 s | dock CSN: DP-17 connected again (HPD low for ~0.2 s) | ≈ 2.97 s |
| +6.67 s | stream re-allocated, mode set done | ≈ 4.05 s |
| +10.3 s | — | 7.703 s port 1 → state 3/4, 7.777 s backlight |

- During the restart the monitor drops HPD for ~0.2 s. DP requires HPD to stay
  asserted unless the sink is powered off; the drop makes the PC remove and
  re-add the monitor (other monitors blank, ~1 s of PC-side set-up). Where the
  firmware or the PM51 drops HPD is not located yet.
- Video is detected at 7.703 s in two separate wakes (identical to the ms)
  although the PC timing differed: the remaining wait is timed by the
  firmware, ~3.6 s after the source is sending again. Power-key start: port 1
  state 1 at 2.10 s → 3/4 at 5.69 s. A third wake detected video at 6.756 s,
  with ports 0 and 1 switching to state 3 in the same main-loop pass (port 1
  `+0x1C` = `0x2E`, `+0x20` = `0x43` at that moment), which points to a common
  gate rather than per-port signal timing.

**Third wake with kernel log** (2026-10-07; firmware log with the main-loop
variable watcher). Port 1 status `+0x20`: `0x03` at 3.10 s, `0x0F` (no
signal) at 3.64 s, `0x03` again at 4.50 s; flags `+0x1C` `0x26` and port 1 →
state 3 at 6.10 s. Kernel log (from the command): CSN disconnect +5.34 s,
connect +5.49 s (the connector came back as DP-18), mode set +7.14 s. With
the firmware start at about command + 2.6 s (stopwatch alignment of run 2)
the disconnect falls at ≈ 2.7 s and the PC's mode set at ≈ 4.5 s, matching
the second `0x03`. Readings:
- the source's stream reaches the port within tens of ms of the PC's mode set;
- the firmware then needs a fixed ~1.6 s (4.50 → 6.10 s; 5.17 → 6.77 s in the
  run before) before it accepts the signal;
- the HPD drop lies after the main loop start (2.06 s) and the first second
  tick (2.36 s), i.e. in main-loop activity, not in the power-up of the board.
  Candidates: the per-port set-up commands to the PM51 (`0x20` sub 0/1/3/12/14
  from `sub_2398F9`, `sub_239618`, `sub_23979A`, `sub_2394DC`). The current
  `diag-log` records every mailbox command between 1.5 and 4.5 s.

**PM51 mailbox commands during a deep-standby wake** (2026-10-07, firmware clock):
0.93 s panel prepower; 1.68 `0x60` sub 0 (data 7); 1.72 / 1.78 `0x20` sub 1
(data `0x0B`, `0x0C`); 1.85 / 1.92 / 1.93 `0x20` sub 12 (data 1, 0, 1); 1.99
`0x60` sub 6 (8); 2.00 / 2.00 `0x20` sub 14 (8, 8); 2.01 `0x20` sub 12 (0);
2.01 main loop; 2.08 `0x70` sub 15 (0); 2.08 / 2.15 `0x20` sub 3 (7, 8); later
entries were beyond the 16-entry log. From the payload/commit anchors of the
third wake the firmware start is ≈ command + 2.65–2.95 s, which puts the dock's
disconnect at ≈ 2.4–2.7 s on the firmware clock; the earlier slow-transaction
log showed `0x20` sub 12 / 14 / 3 commands at 2.2–2.55 s.

**Configuration updates and the HPD drop** (wake 5, 2026-10-07; mailbox
commands 2.1–4.0 s): 2.14 `0x20` sub 3 (8); 2.21 `0x20` sub 12 (1);
2.28 / 2.28 `0x20` sub 14 (8, 8); 2.29 `0x60` sub 2 (8); 2.29 `0x20` sub 0
(data[0] 1); 2.30 `0x20` sub 12 (0); 2.30–2.46 `0x20` sub 3 (7, 8, `0x0B`,
`0x0C`, 0, 0).
- `0x20` sub 12 data 1 / 0 (`sub_2393BD`) bracket a configuration update in
  `sub_2398F9` (per port of the table `0x3B4288`, 6 × `0x18`; the applied copy
  is kept at `0x3B4318`); it is not the HPD control itself.
- `0x20` sub 0 (`sub_23959E`, 9 bytes) is the port configuration sent by
  `sub_239618`; data[0] is the constant 1, data[1] the port type (`+4` of the
  table).
- Correction (2026-10-07): the PM51 is the mailbox server. Its main loop
  (`0x9574`) calls `0x9D02` every pass while its state `XDATA 0x5E6B` = 3
  (awake); `0x9D02` checks `0x1033C0` and runs `0x4C4C`, which reads the
  request (`0x1033C1`–`C9`, data window `0x1033D0`–`EF` in 32-byte blocks),
  executes it (`0x64A4`, arguments from `C2`–`C4`) and clears `0x1033C0`.
  Whether `0x64A4` forwards commands to the MSB3300 front-end is not
  checked.
- DP-correct behaviour on wake: no hot-plug event when the capabilities are
  unchanged (IRQ_HPD for a link retrain only); a long pulse only when they
  change. Next step: capture the update's payload (current `diag-log`).

**Payload of the update** (2026-10-07, identical after a deep-standby wake and
after a power-key start): `0x20` sub 12 `01`; `0x20` sub 14 `08 00 00 00`;
`0x20` sub 14 `08 01 02 8A`; `0x60` sub 2 `08 01`; `0x20` sub 0
`01 08 00 00 00 08 07 00 00`; (`0x20` sub 12 `00`). Port 8 is most likely the
DP input (inference). The firmware therefore re-sends the same configuration
on every start (case (a): fixable in the main firmware).

**PM wake status `0x3AA`** read after the start (2026-10-07): deep-standby wake
`0x04`, power key from soft-off `0x0C`, mains power-up `0x00` (bits 4:2 =
PM51 state at wake: 1 standby, 3 soft-off, 0 cold). Used by `wake-no-replug`.

**`wake-no-replug` results** (2026-10-07):
- v1 (skip the whole port update after a deep-standby wake): no disconnect in
  the kernel log, but the port stayed without signal ("No signal", then
  standby). A menu key later ran the vendor update: picture back, other
  monitor blanked. So the enable part of the update is needed after deep
  standby.
- The `0x20` sub 14 pair is the hot-plug pulse: `sub_23EE83(port, duration)`
  sends (id, 0, 0) and (id, 1, duration) to the front-end for ports with flag
  `0x20000`; for the scaler's own ports it drives HPD low with a timer via
  `sub_20EDCC`. v2 suppresses only `sub_239479` (sub 14) after a deep-standby
  wake.
- v2 (drop only `0x20` sub 14 after a deep-standby wake): after two mains
  starts with this build the PC fell back to 640x480-style modes (EDID not
  read); a power-key restart (vendor path with the hot-plug pulse) fixed it.
  Hypothesis: during the first seconds after a mains start `0x3AA` still holds
  an older value, so the check suppresses the pulse on a cold start too. The
  patch now stores the value it reads at `0x2039F8` (diag-poke readable).
- v2 deep-standby wake test (2026-10-07, kernel log with `drm.debug=0x104`):
  no CSN disconnect, no connector removal, only DP short-pulse (IRQ_HPD)
  handling by the PC at about +0.4–1.4 s and +6 s; picture after 9.3 s
  (stopwatch; 10.2–13.1 s with the vendor pulse). The mains-start EDID
  fallback was not caused by the patch (check read `0x00`, so it did not act).


## 17. LG 28MQ780 comparison and signal acceptance (2026-10-07)

**Method.** Function discovery on the LG runtime (`tools/aeon/funcs.py`, 4052
functions), then matching against ours: exact instruction signatures (980
pairs), call-graph propagation (1393) and a similarity pass between matched
neighbours (1600 of our 2753 functions). Matched: most of the driver layer
(`0x207000`–`0x252000`: scaler, PQ, HDR/CFD, GOP, HDCP mailbox, port and path
handling), `0x270000`–`0x292000`, `0x2A7000`–`0x2AD000`. Not matched: the
application layer (`0x253000`–`0x26A000`, `0x293000`–`0x2A1000`: OSD, power
and standby states, countdown) and the front-end mailbox (`0x238000`–`0x23A000`;
the LG image has no `0x1033C0` mailbox, its DP receiver is driven by the
scaler alone).

Name transfers from LG strings are mostly PQ/HDR/GOP functions (e.g.
`sub_235422` = `HDCPMBX_SetCommonCmd`). Pairs used below:

| Ours | LG | Role |
|---|---|---|
| `sub_22F2C7` | `sub_230177` | path/port task (90 % identical) |
| `sub_23B068` | `sub_24588E` | port monitor |
| `sub_23A7CB` | `sub_24512D` | timing-change check (same logic) |
| `sub_260E0E` | `sub_25E480` | per-port thresholds |
| `sub_23E5C5` | `sub_247F4E` | store thresholds (`+0x18`, `+0x1A`) |
| `0x3B4950`, `0xB0` per port | `0x3FFF40`, `0xB8` per port | port table |

**Signal acceptance** (the fixed ~1.6 s found in the wake logs, §16):
- `sub_22F2C7` runs `sub_23B068` for each port every 20 ms (byte `+0x14`:
  reloaded with 20, reduced by 10 on each 10 ms tick in the same task). Same
  in the LG image.
- `sub_23B068` counts `+0x16` up by one per pass while the port reports a
  signal. A timing change found by `sub_23A7CB` sets status `+0x20` bits
  `0x0C` and flag `+0x1C` bit 0, which sends the port back to state 1. At `+0x18`
  passes the signal is accepted (`sub_23E64A(port, 3)`, port state 3); at
  `+0x1A` passes without a signal the port is declared "no signal" (state 2,
  flags `+0x1C` `|= 6`).
- `sub_260E0E` sets the thresholds by port type (word `+4`):

| Type bits | Dough | LG 28MQ780 |
|---|---|---|
| bit 0 | 10 / 20 | 10 / 20 |
| bit 1 or 2 | 20 / 60 | 20 / 20 |
| bit 3, 4 or `0x400` | 50 / 500 (50 / 200)* | 20 / 100 |
| other (`0x20`: our ports 0 and 1) | **80 / 400** (50 / 200)* | **30 / 100** |

  (accept / no-signal passes of 20 ms; * when settings `+0x48` bit 2 or `flg`
  `0x4551AE` bit 0 is set; `flg` bit 0 is set by `nvram_init` only when the
  EEPROM magic `0x55AA` is missing.)
- Port 1 (type `0x20`) therefore needs 80 × 20 ms = 1.6 s, which matches the
  measured 1.60 s in two wakes. The LG firmware uses 30 (0.6 s) for the same
  port class.
- `port-accept` sets the type-`0x20` accept threshold to 30 (`0x260EDE`,
  one immediate). The no-signal threshold and the other types are unchanged.
- LG's `sub_24588E` has an additional, optional second threshold (global at
  LG `0x538EA4`, used when the retry counter `0x538F65` is set); not present in ours.

**Other comparisons:**
- Delay calls (`sub_241523` / `sub_241505` = LG `sub_24A325` / `sub_24A307`)
  are the same in all matched functions apart from three LG-only short
  delays; the Dough driver layer has no extra fixed waits.
- `sub_22F2C7`, transition path → state 2: ours `sub_21C8C1(0x20, 2)`, LG
  `(0x28, 0x14)`; LG also retries the path set-up up to 3 times. Meaning of the
  arguments not analysed.
- Most other differing immediates in matched functions are board-specific
  (register addresses, resolution limits 1920 vs 1280, structure sizes).

**Order and parallelism** (LG vs ours, 2026-10-07):
- Low-level start-up (entry `0x26F528` / LG `0x271520`): same calls in the
  same order.
- Application main (`sub_261FDE` / LG `sub_25EDCE`): LG has no front-end
  set-up (our `sub_261FA8` and the mailbox transactions, ~0.9 s after a
  power-key start, 4.6 s after a mains start) and no logo path. Main loop: in
  both, a 10 ms tick handler plus one pass of all tasks; the port task runs
  every pass.
- Panel power: LG runs it as a separate, non-blocking state machine in the
  main loop (`0x2B57BA`, state byte `0x544078`, timestamps from `0x2AA914`),
  started before the loop. Its steps are dispatched by `0x284C62(step)`:
  - step 1 `0x24F973`: output mode 2 and VLCD (`0x44B` bit 5) on, then a
    short wait (panel-table value);
  - step 2 `0x24FA39`: eDP on, 10 ms, HPD poll and training (`sub_210765` =
    our `sub_21177B`), then a 550 ms timer;
  - state 3 waits non-blocking for a panel-table time, then step 3
    `0x24F8AC` (output mode 0, panel-ready flag `0x538FA0`).

  Input detection keeps running during the panel waits. Ours does the same
  steps blocking in `sub_245919` (25 + 10 ms + training + 550 ms busy-wait). With
  `panel-prepower` this happens at `0x2620CC`, before the main loop: in the
  deep-standby wake log the prepower started at 0.93 s and the first mailbox
  command followed at 1.68 s, so the front-end port enable (`0x20` sub 0,
  2.29 s) comes ~0.75 s later than it could. Whether the port enable is on
  the critical path after a wake with `wake-no-replug` is not measured yet.
- LG panel-off `0x24F8C8`: backlight off, 100 ms (ours 320 ms), mode 2
  (ours 1), 80 ms, mode 0, eDP off, 10 ms (ours 20), VLCD off, 1200 ms off
  timer (`0x538FAA`); otherwise the same order as our `sub_245860`.

**`panel-prepower` v2** (non-blocking, after the LG model): boot runs the
vendor panel-on up to the link training, starts a 550 ms countdown (ISR timer
slot 8) and returns, so the main loop and the front-end port set-up start
~0.55 s earlier. The main loop then sets `pnl` = 1 and output mode 0 (vendor
order). A panel-on before the countdown ends waits for the rest, so training
→ backlight stays ≥ 550 ms; a panel-off during the countdown runs normally.
Whether this shortens the wake depends on the port enable being on the
critical path (not measured yet).

**Results** (2026-10-07, stopwatch; build: final list + `port-accept` +
`panel-prepower` v2): deep-standby wake (`kscreen-doctor` enable → picture)
6.8 / 6.9 / 6.7 s (with `wake-no-replug` alone 9.3 s); power-key start 6.6 s
(before 8.4 s); mains start ~11.9 s (an earlier mains start: 11.0 s; single
runs, not comparable in detail). The gain on the wake (~2.5 s) is larger than
the two changes explain on their own (1.0 s + up to 0.55 s); not verified
without a timing log. Power-off by key works only ~3 s after a start (same with
the stock firmware).

## 18. Space for patch code (2026-10-07)

- **Flash** is not the limit: the patched deflate stream must end before
  `0x124D0B` (size word, then a mostly empty TEL entry and `SECU_R2`); current
  builds compress ~5.5 KB smaller than stock.
- **RAM** is: the runtime image fills `0x200000`–`0x453E78`, and the start-up
  code clears the BSS from `0x453E80`. Code appended to the image would be
  cleared or overlap variables; relinking is not possible.
- Usable areas inside the image: the linker padding `0x203800`–`0x203FFF`
  (regular patches; nearly full) and two zero areas of the uncompressed head,
  `0x201214`–`0x201FFF` and `0x202087`–`0x2037FF` (~9.5 KB). The boot loader
  copies the whole `0x3800`-byte head to `0x200000`; the only code
  references with these values are register offsets added to the RIU base
  (`0x201D00`, `0x203034`) and the TEL table read at `0x202000`–`0x202086`.
  `diag-log` and the `diag-poke` tables are the first users (diagnostic
  builds); regular patches stay in the padding until this is hardware-proven.
- **Dead code:** recursive descent from the entry points, interrupt vectors and
  code pointers in data reaches 87.6 % of `0x203800`–`0x2AE000`; ~85 KB in 103
  runs ≥ 64 bytes are not reached. They look like code (few zero bytes, some
  with prologues): either unused SDK code or code reached through tables the
  analysis does not resolve. Not used for patches: proving a block unreachable
  needs a reference check per block, and a wrong guess fails only when the
  rare path runs.

## 19. Timing log of a deep-standby wake (2026-10-07)

Build: final list + `port-accept` + `panel-prepower` v2 + `diag-poke` +
`diag-log` (head-area version). Stopwatch `kscreen-doctor` enable → picture
6.8 s; log (firmware clock):

| Time | Event |
|---|---|
| 0.113 | main init start |
| 0.894 | init done (EEPROM, scaler) |
| 0.911–0.966 | `0x80` sub 4 (`0x0B`, `0x0C`); front-end set-up done |
| 0.981–1.180 | boot panel preparation (VLCD, eDP, training; 550 ms countdown from here) |
| 1.180–1.508 | `0x20` sub 1 ×2, sub 12 ×4, `0x60` sub 6 (~66 ms each) |
| 1.511 | main loop |
| 1.511–1.787 | `0x70` sub 255, `0x20` sub 3 ×2, update: sub 12 begin, `0x60` sub 2, **sub 0 enable 1.784**, sub 12 end (no sub 14: `wake-no-replug`) |
| 1.800–2.081 | `0x20` sub 3 ×6 (~69 ms each) |
| 2.151 | `panel-prepower` ready (main loop blocked by the mailbox until then; not on the critical path) |
| **2.380** | port 1 status `0x03` (signal), 0.60 s after the enable |
| **2.983** | port 1 state 3 → 4 (accepted), 0.603 s = 30 × 20 ms (`port-accept`) |
| **3.059** | backlight on |

So 6.8 − 3.06 ≈ 3.7 s pass between the `kscreen-doctor` command and the
start of the firmware clock (PC-side link start, PM51 wake, boot loader).

**Mailbox speed:** after a deep-standby wake (and after a power-key start,
2026-10-06) every transaction takes 66–69 ms; after a mains start (log of
the same day: `0x80` sub 4 `0x0C` waits 4.56 s for the cold PM51, then)
4–6 ms. The PM51 code path is the same (`0x4C4C`; no fixed waits, the copy
loops are short). Working hypothesis, not verified: the PM51 runs ~13×
slower after leaving standby (clock source or divider set for standby and not
restored). Candidate: `sub_7E4C` (`0x0391`/`0x0372`/`0x03B8` 2-bit fields;
standby entry calls it with 0 or 1, the wake path `0x745A` with 1). The 9
transactions before the port enable cost ~0.55 s more than at mains speed.
Check: compare PM registers `0x0300`–`0x04FF` after a mains start and after a
wake (`tools/regdump.sh`).

**PM register comparison** (`regdump.sh` 0x300–0x3FF, 0x400–0x45F, picture
on; mains start = fast mailbox, deep-standby wake = slow; 2026-10-07). Equal
in both: the `sub_7E4C` fields (`0x0391` 0x80, `0x0372` 0, `0x03B8` 0), so that
candidate is out. Different (mains → wake):

| Reg | Mains | Wake | Writer / note |
|---|---|---|---|
| `0x0387`/`0x0388` | `AA 55` | `00 00` | PM51 `0x96D5`–`0x96F7` |
| `0x038A` | `40` | `C0` | bit 7: PM51 `sub_88EB` (wake transition); `sub_9864` writes `40` |
| `0x0393` | `00` | `01` | `sub_88EB` writes `01`, `sub_9864` (standby side) `11` |
| `0x039D` | `64` | `24` | bit 6: main CPU at standby entry, cleared by `sub_9864` |
| `0x03A4` | `E1` | `00` | ? |
| `0x03AA` | `00` | `04` | wake status (known) |
| `0x03BF`, `0x03C0` | `00`, `03` | `10`, `01` | ? |
| `0x03C3`, `0x03C5` | `4D`, `43` | `00`, `00` | ? |
| `0x03E3`/`E5`/`E7`, `0x03ED`, `0x03EF` | `2D`/`0E`/`0D`, `86`, `00` | `00`…, `00`, `80` | ? |
| `0x03FF` | `00` | `02` | PM51 `0x952C`: bits 1:0 cycle 0–2, period from `0x5E5D` |
| `0x0416` | `10` | `1D` | PM51 `0x6622` writes `ED` |
| `0x0432` | `70` | `F3` | ? |
| `0x044A`/`0x044C` | `00`/`FF` | `C6`/`39` | pins: bits 7/6/2/1 driven only after a wake |

`sub_88EB` (called by the PM51 power state machine `0x3EB4` on the wake
transition, and by `0x980D`) also writes `0x101ED0` = `0x0030`, `0x101F09` =
`0x1C` and `0x100FB4` = 0. The meaning of `0x0393` is unknown.

**The PM51 forwards mailbox commands:** `0x64A4` builds a message
(XDATA `0x5F86`…), sends it byte by byte through `0x9A3F` (non-standard
SFRs `0x9A`–`0x9C`, i.e. a second serial port; interrupt flag `0x20.5`) and
waits for the answer (`0x565A`, buffer `0x5CE4`, time-out `0x5E59`). The
other end is most likely the MSB3300 front-end. So the 66 ms can come from
the PM51 (clock/baud) or from the other chip's response time after its own
standby; not decided.

**Mailbox log over a longer run** (`diag-log-mb`, 2026-10-07): from ~160 s
to ~530 s after a deep-standby wake the only transactions are `0x20` sub 18,
posted every ~8.4 s (sometimes twice within 0.05–0.3 s) by `sub_239302`
(called from the main-loop task `sub_20D134`, two data bytes) with r8 = 0,
i.e. without waiting for an answer (`mailbox_query` returns at `0x239147`
right after writing the request), so their "0 ms" says nothing about the
transfer speed. A `kscreen-doctor` disable/enable without standby produced no
other transaction. The log changed while it was read (~6 min for 512 bytes),
so its order is mixed. `diag-log-mb` now skips posted messages.

## 20. Port wake: our PM51 vs LG 28MQ780 (2026-10-07)

**Report:** a friend's monitors (latest build, no diagnostics; USB-C through a
dock, DP directly from a GPU) stayed in standby (no LED/panel change) when the
USB-C source became active; a manual wake made USB-C work; the stock firmware
woke. Since nothing woke, `wake-no-replug` (main firmware) is not involved;
the PM51 wake decision is. Event 2 (port activity) comes from PM `0x0386`
bit 5 (with `0x038B`) or `0x038B` bits 2:0 (`0x5CCA`/`0x5D31`);
`pm51-wake-recheck` re-reads exactly these after 200 ms and stays asleep if
they are clear. A one-shot event, or bits that clear on read, are lost: most
likely cause (not verified on the friend's monitor).

**LG 28MQ780 PM51** (flash image `0x11080` bank 0, `0x21080` bank 1; same
SDK, event code at XDATA `0x5425`, ours `0x5E89`):
- Event classifier `0x427E` (ours `0x5BAA`): on port activity it finds the
  port (`0x8E98`) and raises event 2 only if the monitor is in automatic input
  mode (`0x53A1` bit 0; the port is stored in `0x5426`) or the port is the
  selected input (`0x5426`/`0x5427`). Activity on other ports does not wake.
- Wake decision `0x7FF0` (ours `0x745A`): event 2 → `0x5C68` (ours: stub
  `0x9D54`, always wake). `0x5C68` measures the signal on the scaler's own
  receiver before waking; details and corrections in §21.
- Our PM51 also keeps the wake event and port: on the wake transition
  `0x40F4` copies `0x5E89`/`0x5E8A` to `0x5E8B`–`0x5E90` (hand-over to the
  main firmware: §21).

**Automatic input selection:** "No signal" takes 30 s+ with "Select
Automatically" and less with a fixed input (friend's report). The no-signal
threshold per port is 400–500 passes of 20 ms (8–10 s) in our firmware and 100
(2 s) in LG's for the same port classes (§17); scanning several ports adds up.

**Stock input filter for port wake** (main firmware → PM51): at power-save
entry (`0x2613EB`) the main firmware writes a port mask into the hand-off block
`0x48A740` +4: settings `+0x4F` = selected input + 1 → mask `~(1 << input)`
(only that port may wake); `+0x4F` = 0 (automatic input) → mask stays 0 (all
ports). +2 is the current port (`0x47FAF5`), +8…+0xF settings `+0xBF`…`+0xC2`.
The PM51 reads the request from the mailbox registers (`0x8958`: 24 bytes
from bank `0x1033` into XDATA `0x5E93`…) and, for command 1 (standby), copies
word 2 (`0x5E97`) into its suppress list `0x5E81+port` (`0x41A8` → `0x95CB`),
which the port finder `0x7D10` honours. **Correction (§21):** in our PM51 this
does not filter the wake. The finder skips suppressed ports but then returns
port 5, and event 2 is raised in any case. LG filters in the classifier instead.

**PM51 time base:** the timer interrupt `0x2511` (1 ms) reloads `0x16`/`0x17`
from 1000 and sets bit `0x21.0` every second; the task `0x880F` (run by the
awake loop `0x9574` and by the sleep loop `0x9BA5`) increments XDATA `0x5E5E`
per second. `0x5E5E` is cleared at PM51 start (`0x9D88`) and read nowhere.
No PCON idle/power-down is used: the sleep loop polls the event classifier.

**`pm51-wake-window`** (replaces `pm51-wake-recheck`): `0x5E5E` saturates at
255 (`0x882C`), is cleared when the standby request is processed (`0x41A8`),
and the event-2 check `0x9D54` wakes only if `0x5E5E` ≥ 5 (s). Re-entering
sleep after an ignored event does not restart the window.

**`port-nosignal`** (untested): the no-signal thresholds (port `+0x1A`, set in
`sub_260E0E`: 400 for type `0x20`, 500 for types bit 3/4/`0x400`, 200 in the
flag case) become 200 passes (4 s). On a no-signal decision `sub_23E64A`
sets the port state 2 and every input path that uses the port (port `+0x12`
mask) path state 5, which `sub_22F2C7` hands to `sub_23ADAF`. That the
automatic scan advances per port on this decision is inferred from the
timing (30 s+ over 3–4 ports), not traced.

**Front-end port ids and the start-up HPD sequence:** the front-end port table
`0x3B4288` (6 × `0x18`) holds the front-end id at +4 and a type at +8:
id 7 (type 8), id 8 (7), `0x0B` (1), `0x0C` (3), 0 (4), 0 (2). Id 8 is the DP
connector (the id in the update of a DP wake); id 7 is USB-C (main-firmware
port 0; confirmed by the PM51 wake port, §22). `sub_268668` (start-up, flag set) sends
`(id, 0, 0)` (HPD low) for ids 7, 8, `0x0B`, `0x0C`, 0, then the port
configuration (`sub_239223`; table entries 3 and 4 depend on settings
`+0xC5`/`+0xC6`), then `(id, 1, 650)` for all. Whether `(id, 1, 650)` only
releases HPD or is itself a pulse (650 µs would be an IRQ_HPD) is unknown;
the front-end firmware (`010F`) contains a "Short HPD" path.

**`wake-no-replug` v3:** drops only `(8, 0, 0)` after a deep-standby wake;
v2 dropped every sub 14 command (all ports) in that window.

## 21. LG robustness features re-checked

**LG wake check `0x5C68` (PM51), fully traced.** Argument 0/1 selects the
candidate port from `0x5426`/`0x5427`.
1. Port index ≤ 6 and type ≤ 10, else no wake.
2. Receiver set-up writes (`0x2B7C` with `0x36`/`0x34`), 30 ms.
3. Config bit 2 of the port's type word (code table `0x2830`, the same layout
   as ours at `0x2928`; never set on either monitor), then mux/port selection
   (`0x3A2B`, `0x8A61`, `0x97DB`) and port set-up `0x585B`.
4. 150 ms, then the measurements:
   - `0x9624`: a clock measurement; above 340 → no wake. Unit and purpose
     not identified.
   - `0xA6DA`: a 14-bit value at receiver offset `+0x40`.
   - `0xA707`: a 13-bit value at `+0x3E`, read from the scaler's receiver
     registers `0x17xxxx` (per-port base `0x0200`/`0x0400`/`0x0600`).
5. Wake if the first value is neither `0x3FFF` nor ≤ 10 and the second is
   neither `0x1FFF` nor ≤ 200, i.e. a measured, non-overflowing timing (most
   likely line period and lines per frame).
6. Alternatively wake if:
   - a PM detect bit (`0x9449`);
   - a receiver status (`0xA25C`, bits `0x88`);
   - and `0xA5BC` bit 1
   
   are all set.
7. Under some receiver status (`0xA25C`, `0x9AF1`, `0xA67F` bit 1) it drives
   the port's HPD low for 100 ms (`0x80C3`).

The earlier note "tests status bit `0x04`" (§20) was wrong: that is the static
config flag.

**Our PM51 has the same SDK helpers but does not use them.**
- `0x97B3` = LG `0xA6DA` and `0x97E0` = LG `0xA707` are only called once each,
  with argument 0, from the list at `0x7BC0`.
- The check itself is replaced by the stub `0x9D54`.

**Port wake in our PM51 is not filtered by input.**
- The finder `0x7D10` only matches ports whose type has bit 1/2/3 set (ports
  2–5 = PM ports 1–4: `0x0386` bit 5 → port 5; `0x038B` bits 0/1/2 → ports
  4/3/2). Ports 0 and 1 (type `0x20`; in the main firmware port 0 → front-end
  id 7, port 1 → id 8 = DP) are never matched.
- When no unsuppressed port matches, it returns 5.
- `0x5D31` then raises event 2 regardless, and `0x9D54` always wakes. So the
  stock suppress list only changes the reported port.
- A second port path, event `0x0A` (`0x6E0A`, only if `0x5E6D` bit 1: `0x53EC` shifts right, then bit 0 is tested), does
  return "none" for suppressed ports.

LG's classifier (`0x44EA`…`0x45B9`):
- automatic input (`0x53A1` bit 0): stores the found port in `0x5426` and
  raises event 2;
- fixed input: raises event 2 only if the found port equals `0x5426` or
  `0x5427`;
- then measures that port (`0x5C68`).

**Why the LG check cannot be copied as is.**
- On this monitor the inputs are on the MSB3300. Input selection and HPD are
  front-end mailbox commands (§20), so the scaler receivers see only the
  MSB3300's output.
- The PM51 port table gives no PM detection to ports 0/1, which carry USB-C and
  DP in the main firmware.
- Which PM bit a DP or USB-C source actually raises on this board, and whether
  the MSB3300 drives its output during standby, are unknown. A measurement on
  the scaler receiver could therefore never see the source and block every
  port wake.

**Wake hand-over to the main firmware.**
- `0x879C` writes `0x5E8B`–`0x5E92` to RIU `0x103380`–`0x103387` (byte-swapped
  words): event at `0x103380`, port at `0x103384`, flags (`0x5E91`) at
  `0x103386`.
- At start, `sub_20E254` (from `sub_2411B5`/`sub_2414AE`) copies them to RAM
  `0x453C74`–`0x453C7B` if RIU `0x10181E` == 2, otherwise it clears them.
- `sub_23D51C` returns the event word, used in `sub_22F2C7`'s helpers,
  `sub_261FDE` (event `0x14`), `sub_2676B2` and `sub_239B2D`. Nothing reads the
  port.
- LG has the same copy (`0x20C4F1`, 10 bytes) and a port getter `0x246FA6`
  that is never called. Neither firmware uses the wake port for the input
  choice.
- `diag-poke` reads RAM page `0x453Cxx`, so event (`0x453C74`) and port
  (`0x453C78`) can be read after a wake.

**LG path set-up retries (`sub_230177`, ours `sub_22F2C7`, state 1).**
- `sub_21D946`/ours `sub_21C8C1` waits a number of frames from the measured
  frame period: LG (0x28, 0x14) = 20 frames, ours (0x20, 2) = 2 frames.
- LG then reads a receiver status (`0x20CF6F` → `0x234480`, front-end types
  ≤ 3). If bits 1:0 are set and fewer than 3 retries were made, it restarts the
  port (+0x1C bit 0) and increments `0x538F65`.
- In the port monitor `0x24588E`, a non-zero `0x538F65` requires a second
  stable count `0x538EA4` before accepting: 100 passes (2 s), or 300 (6 s) when
  the PM wake event is `0x12`. It then resets to 100.
- Ours has no matched counterpart of `0x20CF6F` and no retry. On this board, the link
  that LG checks there is the MSB3300 → scaler link, not the source link. Not
  ported: it would add ≥ 0.3 s per set-up and 2 s after a retry without a known
  failure it would fix.

**Automatic scan.** The decision that moves to the next input on "no signal"
was not found as an LG-matched function. Ours calls application code
(`0x245785`/`0x245787`/`0x245919`, `sub_2676B2`, `0x23EC38`, `0x23AD3C`,
`0x267D13`) from `sub_23ADAF`, which has no LG counterpart. Not traced further.

## 22. Front-end wake messages and front-end failure handling

**Source wakes are front-end messages (event 9), not PM port activity.**
- Measured with `diag-poke` (RAM `0x453C74`): wake from deep standby via DP →
  event `0x09`; via USB-C (dock) → `0x09`; first start after flashing → 0.
- Event 9 path: `0x7EE5` receives a serial frame from the front-end
  (`0x565A`). Command `0xF0` goes to `0x8A89` → dispatcher `0x5ED5`. Message
  type 0 (`0x5F89`) sets `0x6332` bit 0 and stores 24 bits from the message in
  `0x6208`.
- The classifier (`0x5CED`) turns that into event 9. The port comes from
  `0x69B3`: a bit mask in which bit 0 → front-end id 7, bit 1 → id 8,
  bit 2 → 9, bit 3 → `0x0F`, … matched against the PM51 port table.
- The wake decision `0x745A` wakes on event 9 unconditionally.
- The front-end, which owns the connectors, therefore decides that a source
  is active, as LG's PM51 does with its own receivers.
- Consequences:
  - `pm51-wake-window` and `pm51-wake-recheck` act only on event 2, so neither
    affects these wakes.
  - The USB-C no-wake reported with `pm51-wake-recheck` (§20) is therefore not
    explained by that patch if those wakes were also event 9. The friend's
    front-end firmware version at that time is unknown.
  - An input filter belongs on the event-9 bit mask (front-end ids), not on
    the PM bits.

**Mailbox wait budget (main firmware).**
- `mailbox_query` (`0x238FA5`) loads the shared counter `0x4551C8` with 10000
  for each phase: PM51 idle (`0x1033C0` = 0), request data, answer. The 1 ms
  ISR `0x240C55` counts it down, so each phase waits up to 10 s.
- The function returns 0 on a timeout. The 22 call sites are thin wrappers
  that pass the result on as a boolean; whether their callers react was not
  traced.
- No "front-end missing" state and no shorter retry budget were found.
- The PM51 side retries a forwarded command up to 5 times with 100 ms pauses
  (`0x8A5E`…`0x8A84`).
- With a front-end that does not answer, every start-up command can
  therefore cost seconds, which fits a start that hangs for minutes on the
  logo (not measured).

**Failed front-end update (owner's friend, V108).**
- The second monitor hung on the logo after "Processing update...", also
  after a mains cycle. At some point there were no USB devices and no
  reaction to keys.
- It later started with no working input and an all-yellow OSD.
- Flashing V108 again (with "Processing update...") restored it.
- Observations: the scaler-side update works while the front-end firmware is
  broken. Neither the scaler's factory image (`0x000000`–`0x150000`, V107) nor
  any package without `010F` contains front-end firmware. A copy of the
  last-flashed `010F` stays in the scaler flash after a shorter package (only
  the package length is erased), but nothing is known to use it as a fallback.
- Whether the MSB3300 has its own flash, a boot ROM recovery, or a second
  firmware copy is unknown. Why the OSD turned yellow is unknown.

**`pm51-input-filter`** (untested): the event-9 path's call of `0x69B3`
(`0x5D05`) goes to a filter at PM51 `0xA140`.
- Only for event 9 with a non-zero mask: it sets bit 7 on the front-end ids
  (XDATA `0x6202+port`) of the ports in the suppress list, calls `0x69B3`,
  then clears bit 7 on all six ids again.
- If no unsuppressed port matched (result 5 with port 5 suppressed), the event
  is dropped: `0x5E89`, `0x6208` and `0x61E9` are cleared and the code
  continues at the classifier tail `0x5D1F`, which reports no event.
- With "Select Automatically" the suppress list is empty and the result is
  the stock one.
- The selected input in settings `+0x4F` is the port index + 1:
  `sub_2678D9` calls `sub_23F836(path, +0x4F − 1)`, which sets the path's
  port (`+0x28`).

**Tests 2026-10-07 (build with `port-nosignal` v2, `pm51-input-filter`, diagnostics):**
- Input fixed to DP, output disabled with `kscreen-doctor`: "No signal"
  appears; about 4–5 s later it disappears and reappears briefly. This
  repeats, and the monitor never reaches standby.
- Automatic input: standby after the longer scan, then a wake shortly after,
  with event 9 and port 1 (DP).
- v2 gave ports 0 and 1 different no-signal thresholds (8 s / 4 s).
  `port-nosignal` v3 keeps both at the vendor value and shortens only ports
  2–5. Traced afterwards: the two ports are separate receivers, and a
  detached port is not monitored, so the coupling assumed here is not
  supported; the cause is open (see "Ports, receivers and input paths").
- `0x453C74`/`0x453C78` are copied only at firmware start (`sub_20E254`). A
  key press in link-held standby does not restart the firmware, so the values
  read after it are those of the last start.

**Ports, receivers and input paths (traced).**
- Port table `0x3B4950` (6 × `0xB0`), receiver id at +0, type at +4.
  `sub_20E73A` maps receiver id → scaler receiver index (jump table
  `0x2ADF30`: id 0 → 7, 1 → 0, 2 → 1, 3 → 2, 4 → 3, 5 → 4, 6 → 5, 7 → 6).
  Port 0 (USB-C, id 5 → receiver 4) and port 1 (DP, id 6 → receiver 5) are
  separate receivers with their own counters, thresholds and status;
  `sub_23B068` reads each through its own receiver id.
- Input paths: record `0x4821AC + path × 0xA8`, +0x28 = port
  (`sub_2227E2`). `sub_23F836(path, port)` switches a path: the old port is
  detached (`sub_22DDA4` → `sub_22ACFC`: +0x12 path mask bit cleared; when
  no path is left, +0x10 = 4, +0x12 = 0, port state +0x0C = 0), the new one
  attached (`sub_225F48` → `sub_227024`: +0x12 |= 1 << path, +0x10 = path).
  `sub_2678D9` selects the port settings `+0x4F` − 1 for the main path
  (settings `+0x5A`).
- `sub_22F2C7` runs the port monitor only for ports in state 1 or 2, so a
  detached port (state 0) is not monitored. A port's state change is passed to
  every path in its +0x12 mask (`sub_23E64A`: no signal → path state 5,
  accepted → path state 1/2).
- In `sub_23B068`, a port whose receiver reports nothing (`sub_23EDA4` → 0)
  has its counter set to the no-signal threshold after 50 passes (1 s; 5 in
  the flag case), so it gives up after about 1 s whatever +0x1A says. Only
  ports with activity wait the full +0x1A.
- Consequence for `port-nosignal` v2: with the input fixed to DP, port 0
  should be detached and idle, so its threshold should not matter. The "same
  main-loop pass" observation (§16) does not prove a coupling (both inputs
  carried the same PC's output in that test). The cause of the v2 loop is
  therefore open; `diag-log-ring` is meant to capture it.

## 23. Other monitors with the same scaler (reference firmware, not in the repo)

Packages supplied by the owner (2026-10-07). They are kept outside the
repository and must never be flashed onto this monitor.

| Monitor | Package | Scaler | Front-end section `010F` | Notes |
|---|---|---|---|---|
| Tempest GP27U (GP27-FUS, 4K) | `MERGE.bin` v1.45, build May 6 2024, 2,162,524 B | MST9U, **same package layout** as ours (`es07fw.py info` parses it; checksums OK) | yes: offset `0x157F48`, size `0x0B8008`; front-end build Aug 29 2023 (V108's: Nov 17 2022), same debug strings (HDMI 2.1 FRL, DSC, MST) | very likely the same MSB3300-class front-end |
| KTC M27T20 | `MERGE.bin` v3.0.4A, build Apr 12 2023, 1,361,364 B | MST9U, **same package layout** as ours | no; no front-end mailbox (`0x1033C0`) use and no serial front-end path in its PM51 | inputs most likely direct to the scaler (like LG); not the MSB3300 combination |
| KTC M27P20P (Euro, v2.0.3A) | `M27P20P_Ger 2.0.3A-6E82.bin`, build Apr 10 2023, 1,989,724 B | MST9U, same package layout | **yes**: `0x12DC48`, size `0x0B8008`, front-end build Feb 6 2023 (GP27U: Aug 29 2023, same size; V108: Nov 17 2022) | **same chip combination as ours** (PM51 serial front-end path and LG-style event-2 check as GP27U; same port table: ports 0/1 type `0x20` with front-end ids 7/8, ports 2–5 ids `0x0B`–`0x0E`). GP27U and M27P20P are sister firmwares (identical front-end command set) |
| ASUS PA279CRV (MCM107) | `ASUS_PA279CRV_MCM107_20260424_ISP_E547.bin`, 1,395,804 B | MST9U ("MST9U5" string), TEL table at `0x22080` (different head layout) | no | USB-C role handling strings; USB hub GL3523; no front-end chip |

**GP27U compared with ours (first pass):**
- PM51: the front-end message path is the same (dispatcher `0x627C`, queue
  `0x5A59`, event 9 → wake unconditionally in the wake decision `0x855C`ff).
  The classifier checks the queue first (ours last). Port activity (event 2)
  uses the same finder without an input filter, but the wake decision calls
  a real LG-style check (`0x425E`: port set-up, 30 ms, measurement) where
  ours has the stub `0x9D54`.
- Main firmware: `mailbox_query` (`0x23BA85`) is identical to ours (10 s per
  phase, no failsafe).
- Front-end commands (approximate constant scan of the 22 call sites each):
  - GP27U only: `0x10` sub 2 and 7, `0x20` sub `0x14`, `0x50` sub 7,
    `0x60` sub 9.
  - Ours only: `0x80` sub 1, 2 and 4, `0x60` sub 0 and `0x10`.
  - Meanings not traced.

## 24. Front-end commands and the automatic input scan

**GP27U-only commands are all posted** (no answer awaited, r8 = 0):

| Command | Wrapper (GP27U) | Data sent | Callers |
|---|---|---|---|
| `0x10` sub 2 | `0x23BEAC` | 2 bytes (r3, r4) | `0x23C13A`, `0x23C68C`, `0x23C9E9`, `0x279A36` |
| `0x10` sub 7 | `0x23BE82` | 1 byte | `0x23C13A`, `0x23C68C`, `0x279A36` |
| `0x20` sub `0x14` | `0x23BD03` | 4 bytes (u32) | `0x249C5A` |
| `0x50` sub 7 | `0x23BDF8` | 2 bytes | `0x23C13A` |
| `0x60` sub 9 | `0x23BF68` | 4 bytes | `0x23C13A`, `0x23C68C` |

None of them is a status query; meanings not traced.

**Front-end queries in ours** (answer awaited):
- `0x30` sub 7 (`sub_23956D`): sends a connector id (1 byte) and gets 1
  byte back, apparently the front-end's own index for that connector.
  `sub_268453` maps ids 1–9 this way at start-up.
- `0x60` sub `0xB`: sends that index and gets 1 byte back. Used only by the
  standby gate `sub_2612F9`:
  - only for the current port, when the port type has bits `0x20000` and
    `0x20` (DP class: DP, USB-C);
  - takes the id from `0x3B427B[port]`, maps it with `0x30`/7, then queries
    `0x60`/`0xB`;
  - correction (2026-10-08, §29): the gate returns 1 (refuse) when the
    answer is **0**; answer 0 = a source is active on the connector,
    1 = no source (standby allowed).
  - GP27U has the same pair (`0x23C08F`, gate `0x26BAD6`).
- `0x70` (`sub_2399DD`): answers 4 bytes, read as two u16.
- `0x80` (`sub_239A84`): answers 1 byte.
- DDC/CI is handled in the main loop (`sub_26AD19` ← `0x20CF68` ←
  `sub_20D134` ← main), the same context as all other front-end commands.

**Automatic input scan (ours).**
- `sub_25FE39` (called through a pointer, with a tick counter) handles the
  case settings `+0x4F` = 0 at `0x260012`.
- A per-call counter must exceed 8 (4 in the flag case) while the current
  port shows no signal (`+0x20 & 0x0C`). Then `sub_2653EA(port)` gives the
  next port and `sub_23F836(0, next)` switches path 0; for some port types
  `sub_23EE83(port, 600)` runs first.
- `sub_2653EA`:
  - Normally a fixed rotation 0 → 1 → 2 → 3 → 0 (USB-C → DP → HDMI 1 →
    HDMI 2). The next port's status gets `|= 0x0C`, so it starts as
    "no signal".
  - With `0x4551AC` bit 5 set, it picks the port from SAR ADC channels 6
    and 8 (`sub_23DCE4`) compared with fixed levels. These look like the
    key ladder, so input selection by key (inference).
- GP27U (`0x26AEEA`): next port = (port + 1) mod 6 (`0x270180`), skipping
  ports with type bit `0x1000` without `0x800`.
- Neither firmware asks the front-end which inputs are active during the
  scan. The only per-input status query (`0x60`/`0xB`) is used for the
  standby gate.

**Possible improvement (not built).** In automatic mode, `sub_2653EA` could
query `0x30`/7 + `0x60`/`0xB` for the candidate inputs and go to the first
one whose link is active, falling back to the rotation.

Open questions:
- Does `0x60`/`0xB` answer for HDMI connectors? The vendor queries only the
  DP class.
- What does it report for a DP link held without video (e.g. output
  disabled with `kscreen-doctor`)? The standby gate suggests 1, which would
  make the scan stop on such a port.

A diagnostic DDC command that runs the two queries for a given id would
answer both on hardware.

**Cause of the `port-nosignal` v1/v2 loop** (`diag-log-ring`, input fixed
to DP, output disabled):
- "No signal" (state-4 entry, caller `0x2575C6`) repeated every 4.07 s with
  no port state change in between (port 1 stayed in state 2 after its
  no-signal decision at +4.0 s).
- A port in state 2 keeps being monitored. Its counter restarts, and after
  +0x1A passes it repeats the no-signal decision. Each repeat re-enters
  state 4, and the state-4 entry restarts the countdown, whose pre-standby
  comes 5 s after the entry (vendor and `standby-timeout`).
- With 200 passes (4.07 s) the repeat always comes before the 5 s, so
  standby is never reached. The vendor's 400 / 500 passes (8 / 10 s) leave
  room.
- `port-nosignal` v3 shortens only ports 2–5, to 300 passes (6 s), and the
  generator refuses values below 275. The vendor's own flag case (200 for
  all ports when settings `+0x48` bit 2 or flg bit 0 is set) would have the
  same loop.
- `diag-fe` (VCP 0xED) runs the link query of §24 for any connector code;
  `tools/fequery.sh` queries all four inputs.

## 25. Cross-firmware comparison (GP27U, M27T20, LG)

Function matching (`xmatch`, same method as for LG in §17):
- 2025 of our 2753 functions have a GP27U counterpart and 2035 an M27T20
  one. The library layers (input ports, mailbox, PM helpers) match; the
  application layer (main, front-end set-up, panel power, OSD) is
  vendor-specific and does not.
- GP27U main is `0x26CAE0`; its init (`0x24230B`) matches ours (`sub_23D3EB`).

**PM51 wake transition:**
- `sub_88EB` (writes `0x101ED0`, `0x101F09`, `0x100FB4`, `0x0393` = 01,
  `0x038A` bit 7) is byte-identical in GP27U (`0x955F`).
- All three PM51s (ours, GP27U, LG) write `0x0393` = 01 at wake and 11 at
  sleep entry, so the slow mailbox after a wake (66 ms vs 5 ms) is most
  likely SDK behaviour, not a Dough change.
- `diag-poke` now allows writing `0x0393`, and `diag-fe` measures its own
  two mailbox transactions, so the `0x0393` hypothesis can be tested on
  hardware: after a wake, write 00 and compare the times.
- Power-up step in the PM51 state machine (`0x3EB4`): ours writes regs
  `0x36`/`0x34`, waits 5 ms, polls `0x9C` bit 1 (up to 1 s), then waits
  **100 ms**. GP27U (`0x54F0`ff): no 5 ms wait, then the same poll, then
  **50 ms**.

**Port thresholds** (accept / no-signal passes of 20 ms):

| Port class | Ours (stock) | Ours (patched) | LG 28MQ780 | GP27U |
|---|---|---|---|---|
| type `0x20` (DP/USB-C here) | 80 / 400 (flag: 50 / 200) | 30 / 400 | 30 / 100 | 50 / 200 (60 / 300 with `0x400`) |
| bit 3/4 + `0x400` (HDMI here) | 50 / 500 (flag: 50 / 200) | 50 / 300 | 20 / 100 | 60 / 300 |
| bit 3/4 without `0x400` | as above | as above | 20 / 100 | 60 / 200 |
| bit 1/2 | 20 / 60 | — | 20 / 20 | 50 / 150 |
| bit 0 | 10 / 20 | — | 10 / 20 | 10 / 20 |

GP27U has no flag-case variants. Whether GP27U's or LG's countdown has the
"no-signal ≤ 5 s loops" problem (§24) depends on their state-4 handling,
which was not compared.

**Automatic input scan:** GP27U `0x26AEEA`: next port = (port + 1) mod 6
(`0x270180`), skipping ports whose type has `0x1000` without `0x800`; no
front-end query (§24).

## 26. M27P20P: front-end commands, HPD and the port configuration

**Front-end command inventory** (all mailbox call sites; `xcmp/mbinv.py`):
- GP27U and M27P20P use the identical set.
- Ours additionally uses the `0x80` family (sub 1, 2, 4 posted; sub 3 with
  an answer) and `0x60` sub 0 and `0x10`.
- KTC additionally uses `0x10` sub 2 and 7, `0x20` sub `0x14`, `0x50` sub 7,
  `0x60` sub 9 and `0x70` (r5 `0x10`, posted).
- All share the HPD command (`0x20` sub `0xE`: id, level, duration), the
  queries `0x30`/7, `0x60`/`0xB` and `0x70`, and the port enable `0x20` sub 0.
- KTC's `0x20` sub `0x14` brackets a large routine (`0x24A25B`, ours
  `0x243757`): sent with `0xFFFFFFFF` at the start and 0 at the end when a
  flag is set; purpose unknown.

**HPD (`0x20` sub `0xE`):**
- M27P20P sends it only through `0x2445F8` (= ours `sub_23EE83`):
  (id, 0, 0) then (id, 1, duration).
- The input-select routine `0x2707CB` pulses HPD (600) only for ports
  without type bit `0x20`, i.e. never for DP / USB-C.
- Durations used: KTC 650, 600, 300; ours 700, 650, 600.
- Ours also sends HPD directly from `sub_268668` (start-up: all ids low, then
  high after 650) and from `sub_239618` (the per-port configuration).

**Per-port configuration** (ours `sub_239618`, KTC `0x23CAB2`), for
DP-class inputs (front-end ids 7–9):
- **Ours:** plain enable unless the entry's +0x0E flag is set; with the
  flag and settings `+0x59` = 0: HPD 650, `0x60`/2, enable.
- **KTC:** first reads the wake event (`0x242C4C` = ours `sub_23D51C`,
  stored at `0x44B1E0`).
  - +0x0C set: HPD 650.
  - +0x0E clear: plain enable.
  - +0x0E set: clear bit `0x4000` of `0x44B1D2`, HPD 650, `0x60`/2, enable.
- The +0x0E flags are set by `sub_264633` (KTC `0x26DEDC`, identical logic)
  from a mode value: 0 none, 1 all, 2 entry 0 (USB-C), 3 entry 1 (DP),
  4 entries 0–3. It acts when the mode differs from a cached copy, which is
  in BSS (0 after every start) in both firmwares.
- Ours calls it at start-up in `sub_268453` with settings `+0xA5`.
  `sub_26535A` (via `sub_268BB0`, the Dough-only `0x60` sub 0 command) also
  reads and clears `+0xA5` and pulses HPD (650).
- So the HPD pulse seen at every start (§20 `wake-no-replug`) is most likely
  `+0xA5` ≠ 0 being treated as a change at every start (inference; the
  value of `+0xA5` on the test monitor is unknown). KTC calls the flag
  routine from its setting handlers (`0x272683`, `0x272D79`).

**PM51 power-up:** M27P20P is the same as GP27U (no 5 ms wait, 50 ms after
the `0x9C` poll; ours 5 + 100 ms).

## 27. Link query results, mailbox speed and hot-plug at start-up (2026-10-07)

**Front-end link query on hardware** (`diag-fe`, `tools/fequery.sh`):

| Situation | USB-C (code 8) | DP (code 7) | HDMI 1 / 2 (codes 1 / 3) |
|---|---|---|---|
| index (`0x30`/7), every run | `0x08` | `0x08` | `0x00` |
| link: mains start; deep-standby wake; picture on DP + USB-C | 0 | 0 | 0 |
| link: input fixed to DP, DP output disabled, "No signal" → link-held standby, USB-C active | 1 | (not run) | 0 |

- DP and USB-C map to the same index, so `0x60`/`0xB` cannot tell the two
  connectors apart. HDMI codes give index 0, which the start-up loop in
  `sub_268453` treats as "no front-end index" (it configures only indexes
  1–16), so the query does not cover HDMI.
- Link 1 was seen only while the DP output was disabled and the monitor
  went from "No signal" to link-held standby; it reached deep standby right
  after. (Interpretation corrected in §29: 1 = no source, standby allowed.)
- The conclusion that this query cannot drive automatic input selection is
  withdrawn in §29 (raw mode asks each DP-class connector).

**Mailbox speed (correction to §19 and §25):**
- The two queries take 2–6 ms after a mains start and after a deep-standby
  wake. Writing PM `0x0393` = 0 changed nothing. The PM51 serial path is not
  slow after a wake; the `0x0393` hypothesis is dropped.
- The slow transactions in the start logs are posted `0x20` sub 3 commands,
  sent by `sub_2394DC` (called from `sub_239A35` in the main loop) for every
  bit of the pending mask `0x45504E`, with id `0x3B4281[i]` (7, 8, `0x0B`,
  `0x0C`, 0, 0) and level bit `i` of `0x455050`.
  - The mask is filled by `sub_20EDCC(receiver, level)` for ports with type
    bit `0x20000` (front-end ports). Its callers are the HPD routine
    `sub_23EE83`, `0x23EF7E`, `sub_20F8D9` and the 1 ms timer ISR, so
    `0x20` sub 3 is most likely the hot-plug level of a front-end port
    (inference).
  - Wake log of this day: after the port enable (`0x20` sub 0 at 1.927 s),
    ids 7 → 8 took 5 ms, then 125, 70, 69 and 126 ms for 8, `0x0B`, `0x0C`
    and the first id 0 (time to the next command; posted commands wait for
    the previous one). So the front-end answers slowly while it is busy
    right after the enable, not after every wake.
  - Two of the six commands go to ports 4 and 5, which do not exist on this
    monitor (id 0). Together they block the main loop for ~0.2 s at every
    start (speed candidate; whether the picture comes earlier is not proven).

**Hot-plug at start-up and settings `+0xA5`:**
- Measured `+0xA5` = 1 (`0x482575`), input `+0x4F` = 0 (automatic).
- `+0xA5` is derived from settings `+0xCB` (saved per mode in the profile
  block `+0x659`; OSD action `0x268C20` through the pointer at `0x3B88C4`;
  factory default from `0x26A378`). `sub_268BB0` calls
  `sub_26535A(port, +0xCB == 2)` for ports 1 and 0: `+0xA5` = that value,
  HPD pulse 650 ms (`sub_23EE83`), port configuration from the applied copy,
  `0x60` sub 2 (id, value), then `sub_264633(+0xA5)`; afterwards `0x60`
  sub 0 with (`0x3B42A4`, 1 if `+0xCB` = 0, else 3). So `+0xA5` = 1 means
  `+0xCB` = 2 (inference). Which OSD option `+0xCB` is: not identified.
- `sub_268BB0` runs at start-up only when the wake event is 0 (mains start;
  `0x2620D6`), and from the OSD action. After a deep-standby wake,
  `sub_268453` calls `sub_264633(+0xA5)` instead.
- `sub_264633(mode)` (cache `0x455061` in BSS, so mode 1 is a "change" at
  every start): mode 1 sets the `+0x0E` flag of all six entries of
  `0x3B4288` and marks the entry of path 0's port for an update. Nothing
  clears `+0x0E` later.
- With `+0x0E` set and `+0x59` = 0, every configuration update of a DP-class
  entry (`sub_239618`, ids 7–9) sends an HPD pulse of 650 ms (emulated
  unplug), `0x60` sub 2 and the configuration with the `0x3B43A8` data.
- Open: whether an input switch triggers such an update. `diag-log-ring` v2
  logs mailbox commands for the whole run to show it.

**USB-C at 640×480 after an automatic switch** (DP and USB-C from the same
PC, input automatic, DP output disabled; log 586–608 s):
- 586.0 s DP lost; 594.1 s DP no-signal decision; scan HDMI 1 (594.2),
  HDMI 2 (595.2), USB-C (596.3); USB-C accepted at 602.5 s, i.e. 16.5 s
  after the DP output was disabled.
- The PC showed the USB-C output with 640×480 only, which is what a source
  uses when it cannot read the EDID. If the switch sends the 650 ms HPD
  pulse to USB-C (open, see above), the PC re-reads the EDID at that moment.
  Not decided; the same code is in the stock firmware.
- Two time stamps in that log were wrong (byte 2 read as 0: 4.316 s for
  594.140 s, 5.389 s for 595.213 s), a DDC read error; `tools/logread.py`
  now reads out-of-order entries again and marks them if they stay wrong.

**Second PC on USB-C** (DP from the main PC, USB-C from a second PC, input
automatic; 2026-10-07):
- The `0x30`/7 answer is not a fixed code → index map: it was `0x07` for
  both codes 7 and 8 while USB-C was the selected input, and `0x08` for both
  in all earlier runs, where DP was selected. So it reports the front-end id
  of the selected DP-class connector (USB-C 7, DP 8; two states observed).
  This fits one DP receiver in the front-end that is switched between the
  two connectors (inference). `diag-fe` v2 has a raw mode (value
  `0x100 | id`) that sends `0x60`/`0xB` for a given id without the mapping,
  to see whether the front-end reports the link of the connector that is not
  selected (`tools/fequery.sh r7 r8`).
- Link 0 for all codes with both PCs active.
- Automatic input stays on the current input when another one becomes
  active (DP re-enabled while USB-C was shown). That is the vendor design:
  the scan (`sub_25FE39`) only moves on when the current input has no
  signal; GP27U does the same.
- USB-C output disabled → DP shown after 11.9 s: 8.0 s until the USB-C
  no-signal decision (DP-class threshold 400 passes, vendor value; v3 of
  `port-nosignal` changes only HDMI), 3.1 s until DP reported a signal after
  being selected (2938.2 → 2941.4 s), 0.6 s acceptance. The 8 s can only be
  shortened after the state-4 restart loop (§24) is fixed.
- Ports 0 and 1 reported a signal (status `0x03`) within 30–40 ms of each
  other after each switch in this and the earlier logs; not explained.
- The USB-C 640×480 fallback went away when another input was selected and
  then USB-C again, i.e. a one-time EDID read failure on the PC side; whether
  the monitor caused it is still open.

## 28. Hot-plug pulses at input switches (2026-10-07)

**Link query per connector** (`diag-fe` v2 raw mode, USB-C selected):

| DP from the main PC | `r7` USB-C (selected) | `r8` DP (not selected) |
|---|---|---|
| output active | 0 | 0 |
| output disabled | 0 | 1 |

The front-end reports the state of the connector that is not selected.
(First reading "1 = link up without video" corrected in §29: 1 = no active
source, 0 = active source.)

**Mailbox commands of a manual switch USB-C → DP** (`diag-log-ring` v2;
"pulse" = `0x20` sub 14 (id, 0, 0) then (id, 1, duration), ~5 ms apart):

| Time | Commands | Origin |
|---|---|---|
| 738.74 | `0x20` sub 0 (0, 7), `0x60` sub 2 (7, 0) | detach USB-C: `sub_23979A`, `+0x0E` path (disable) |
| 738.77 | `0x60` sub 6 (8, `+0x9C`), pulse DP, duration 0 | `sub_265A25(0, +0x9C, 0)` from `sub_2678D9` |
| 739.32 | pulse DP (650), `0x60` sub 2 (8, 1), `0x20` sub 0 (1, 8) | attach DP: `sub_239618`, `+0x0E` path |
| 742.49 | DP reports a signal (3.2 s after the attach) | |
| 742.91–743.19 | the whole sequence again (disable DP, both pulses, enable) | a second `sub_2678D9` call |
| 744.35 / 744.95 | DP signal / accepted | |

The switch to USB-C (second PC) had the same two pulses; USB-C reported a
signal 9.6 s later.

- **Pulse A:** `sub_2678D9` (input selection from menu, keys, DDC/CI and
  start-up) calls `sub_265A25(0, +0x9C, 0)`. For front-end ports this sends
  `0x60` sub 6 and `sub_23EE83(port, 0)`. HPD stays low for about the
  time between the two commands; anything over 2 ms is an unplug for a DP
  source. The other callers of `sub_265A25` (`+0x9C` changed, profile
  restore, factory reset) pass 600 or 650.
- **Pulse B:** the `+0x0E` path of `sub_239618` (HPD 650), active because
  `+0xA5` = 1 sets the flags at every start (§27). It also runs on every
  automatic-scan step to DP / USB-C (`sub_25FE39` → `sub_23F836`) and after
  a deep-standby wake. A real `+0xCB` change pulses on its own
  (`sub_26535A`, 650).
- The scan's own `sub_23EE83(port, 600)` (`0x260179`) is only for ports
  without type bit `0x20` (HDMI).
- M27P20P sends no pulse to DP-class inputs at input selection (§26); its
  front-end firmware differs from ours (`010F` sections differ), so that is
  evidence, not proof, that the pulses are not needed.
- The second full selection at 742.9 s is not explained. Candidates:
  `sub_258E5D` (`0x2592C3`, applies the OSD value `0x457857` when it
  differs from `+0x4F` or the path's port is not 0) after the menu action.
  `diag-log-ring` v3 logs every `sub_2678D9` call with its caller.
- Switch cost besides the pulses: `sub_2678D9` → `sub_2676B2(1)` and the
  next main-loop pass put 0.54 s between the selection and the attach.

**Experimental patches** (`tools/patches_src_select_no_replug.py`, untested):
- `select-no-replug` (pulse A): `sub_265A25`'s HPD call goes through a stub
  that returns when the duration is 0. `0x60` sub 6 and the EDID loop stay.
- `attach-no-replug` (pulse B): the HPD call in the `+0x0E` path of
  `sub_239618` is skipped; `0x60` sub 2 and the configuration stay. Risk:
  if `0x60` sub 2 changes what the connector reports to the source, the
  source is not asked to read it again.

## 29. Link query polarity, DisplayPort mode and the menu re-apply (2026-10-08)

**`0x60`/`0xB` answer, corrected.** Raw queries (`diag-fe` v2), DP selected
with a picture:

| USB-C (id 7) | answer |
|---|---|
| second PC, output active | 0 |
| output disabled | 1 |
| cable unplugged | 1 |

With the earlier tables (§27, §28): **0 = a source is active on that
connector, 1 = no active source.** The vendor gate agrees:
`sub_2612F9` ends with `sfnei r7,0; cmovri r7,r0,1`, i.e. it returns 1
(refuse standby, `0x2613A4` → refusal tail) when the answer is 0. The
earlier statement "non-zero refuses standby" (§24) was the wrong way round.
- Consequence: the query does tell, per DP-class connector, whether a source
  is active, also for the connector that is not selected. Automatic input
  selection for DP / USB-C could use it (raw ids 7 and 8). HDMI ids
  (`0x0B`, `0x0C`) are untested.

**Confirmed 2026-10-08** (`diag-poke`): 1.4 → `+0xCB` 2, `+0xA5` 1;
1.4 without DSC → 1, 0; 1.2 → 0, 0. Switching to 1.2 while running gave "No
signal" on the dock-connected PC until a restart by the power key;
switching back to 1.4 worked at once.

**Settings `+0xCB` = OSD "DisplayPort Mode"** (1.2 / 1.4 without DSC / 1.4;
test monitor: 1.4). Three values, and 2 gives `+0xA5` = 1 (§27), so most
likely 0 = 1.2, 1 = 1.4 without DSC, 2 = 1.4 (inference; to be confirmed by
reading `0x48259B`). Then:
- `+0xA5` = 1 means "DSC mode": `sub_264633(1)` marks all entries `+0x0E`.
- In that mode the attach sends `0x60` sub 2 (id, 1) and the detach (id, 0):
  probably DSC on for the selected DP-class connector and off for the other
  one (inference). The connector's capabilities then change at every switch,
  which is why the attach pulses HPD (650 ms): the source must read them
  again. `0x60` sub 0 (`0x3B42A4`, 1 if `+0xCB` = 0, else 3) fits a
  maximum-link-rate setting (inference).
- So `attach-no-replug` has a concrete risk: a source that read the
  capabilities while its connector was not selected (DSC off) is not told
  that DSC is on after the switch.

**PC side of a USB-C → DP switch** (main PC behind a Synaptics MST hub, drm
debug log; build with `select-no-replug`):
- Monitor 519.599 s pulse B (attach) ↔ PC 05:07:30.657 CSN `ddps 0`
  (monitor gone); 05:07:31.352 CSN `ddps 1` (back, 0.70 s = the 650 ms pulse).
- The PC re-creates the connector (DP-16 → new connector id), sets the mode
  (31.86), the desktop sets it again with DSC (payload re-allocation
  33.5–34.45). The monitor locks at 524.66 (≈ PC 35.7).
- Pulse A is gone in this build: `0x60` sub 6 is sent without `0x20` sub 14.
- The second sequence (523.14–523.38: disable, pulse B, enable) produced no
  CSN on the PC side.

**Second selection = vendor retry at menu close.** `diag-log-ring` v3:
518.961 `sub_2678D9` by the OSD action `sub_267A7F`; 523.137 again by
`sub_258E5D` (`0x2592C3`). That path runs when `0x453C70` bit 16 is set and
the menu timer `0x4551A4` (set from settings `+0x7F`, counted down by
`sub_261C04`) has run out, and the selected input's path record
(`0x47FA5C + 0x7C × n`, `+0xF` bit 0) is set; it selects the input again.
Both observed cases were 4.2 s after the menu action, when the input still
had no picture. With pulse B the PC needs longer than that, so every menu
switch to DP / USB-C was done twice.

## 30. Incident: dead state after a deep-standby wake (2026-10-08)

Build: the regular list + `select-no-replug`, `diag-poke`, `diag-log-ring` v3,
`diag-fe` v2; input fixed to DP; DisplayPort Mode 1.4.
- After a wake from deep standby: backlight on, black picture, no "No
  signal" message. Keys and the OSD menu reacted without delay (main loop
  running). DDC/CI failed (`poke.sh`: no answer to GET `0xEA`, `0xEB` read
  back 0), so no log could be read. The PC kept listing the monitor.
- Opening and closing the menu brought "No signal", then standby. From then
  on: no reaction to keys (including power), to source changes or to DDC;
  8.5 W after unplugging the USB-C laptop (link-held standby 13 W, deep
  standby 1.2 W). A mains cycle restored normal operation (DP picture).
- Reading (inference, not proven): the input front-end was not working
  after the wake; the scaler side worked. Correction (same day): the test
  setup sends DDC/CI over USB-B (Dough's DDC-over-USB, independent of the
  video inputs), not over DP, so the DDC/CI failure does not point at the
  front-end; how the USB path reaches the scaler is not traced. The standby entry, which the PM51 performs together
  with the front-end, then did not complete, and the PM51 no longer
  handled keys.
- Changes in this build that touch the wake: `select-no-replug` removes the
  selection's HPD command for DP at start-up (with `wake-no-replug` that
  was a single "HPD high, duration 0"). Not excluded as a trigger.
- `diag-log-ring` v4 logs failed mailbox transactions ("K MAILBOX FAILED"),
  and `poke.sh` / `logread.py` take `TRIES=` for a DDC/CI that answers
  only now and then.

## 31. The front-end does the input switch (2026-10-08)

**Test:** DisplayPort Mode "1.4 without DSC" (`+0xCB` = 1, `+0xA5` = 0),
build with `select-no-replug`; menu switches DP ↔ USB-C.
- Commands per switch: `0x20` sub 0 (0, old id) (disable), `0x60` sub 6
  (new id, 0), `0x20` sub 0 (1, new id) (enable). No `0x20` sub 14, no
  `0x60` sub 2 (the `+0x0E` flags are clear in this mode).
- Result: the screen blanks for ~1 s and shows the DP picture again although
  USB-C is selected; neither PC sees a change.

**Reading:**
- Both scaler receivers (port 0 USB-C, port 1 DP) carry whatever the
  front-end outputs. That explains why both ports always report a signal
  within tens of ms of each other (§27, §28) and why the scaler accepted
  "USB-C" with DP's picture.
- So the switch itself happens in the front-end. In this mode the stock
  firmware sends one more command, the selection's HPD pulse (`0x20` sub 14
  (id, 0, 0), (id, 1, 0) from `sub_265A25`), which `select-no-replug`
  removed. A `0x20` sub 14 command for the new connector is therefore the
  front-end's switch trigger (inference). Whether the "high" command alone
  triggers it is untested.
- In DisplayPort Mode 1.4 the switch worked with `select-no-replug`
  because the attach still sent its own pulse (650 ms).
- `0x60` sub 2 (id, value) is most likely the DSC capability of a connector:
  `sub_26535A` (DisplayPort Mode handler) sends it for DP and USB-C with
  (`+0xCB` = 2); in mode 1.4 the detach withdraws it from the old connector
  and the attach restores it, so the attach must make the source read the
  capabilities again (650 ms pulse).

**`switch-no-unplug`** (`tools/patches_src_switch_no_unplug.py`, untested;
replaces `select-no-replug` and `attach-no-replug`):
1. Selection (`sub_265A25`, duration 0): only (id, 1, 0) instead of the
   pulse.
2. Attach in mode 1.4 (`sub_239618`, `0x239747`): (id, 1, 0) instead of the
   650 ms pulse.
3. Detach in mode 1.4 (`sub_23979A`, `0x239855`): `0x60` sub 2 (id, 0) is not
   sent, so DSC stays advertised on both connectors, as after every mains
   start and DisplayPort Mode change.
A DisplayPort Mode change keeps its 650 ms pulse (`sub_26535A`).

If the front-end does not switch on the "high" command alone, the picture
will stay on the old input as in this test; then the low phase is the
trigger and a switch needs a real (short) pulse.

**Test of `switch-no-unplug` (2026-10-08):**
- "1.4 without DSC": switch commands now include (id, 1, 0) for the new
  connector; the front-end switches (correct picture), 1.4 s from the menu
  action to the accepted signal (USB-C 214.91 → 216.35 s, DP 221.38 →
  222.81 s); no re-plug on either PC. So "HPD high" alone is the switch
  trigger; the low phase is not needed.
- 1.4 (DSC): the detach no longer sends `0x60` sub 2 (id, 0); the attach
  sends (id, 1, 0), `0x60` sub 2 (id, 1) and the enable. No re-plug, the
  other monitor on the dock is not disturbed. Main PC re-plugged while USB-C
  was selected, then DP selected: picture with DSC as before.
- Still to test: automatic input (the scan attaches through `sub_23F836`
  without `sub_265A25`, so in "1.4 without DSC" it sends no `0x20` sub 14
  for DP / USB-C, in stock as in the patch) and deep-standby wakes.

## 32. Automatic input with `switch-no-unplug`, and a stuck standby gate (2026-10-08)

**Automatic input, DisplayPort Mode 1.4 (DSC):** DP output disabled →
scan HDMI 1, HDMI 2, USB-C; the USB-C attach sends (7, 1, 0), `0x60` sub 2
(7, 1) and the enable; USB-C picture after ~2 s. DP re-enabled: the monitor
stays on USB-C (vendor design). USB-C unplugged at 1693.87 s → USB-C
no-signal decision 8.0 s later → DP attach → DP accepted at 1702.70 s,
without disturbing the other monitor. The 8 s are the vendor no-signal
threshold of DP-class ports.

**Automatic input, "1.4 without DSC":** the scan's attach of USB-C sends
only the enable (no `0x20` sub 14: no `+0x0E` flags, and the scan does not
go through `sub_265A25`), yet the front-end switched to USB-C (~3 s). The
difference to the failed manual switch of §31: here the old connector (DP)
had no source any more. So the front-end does switch by itself when the
routed connector loses its source, or on the enable in that case
(inference); the HPD command is needed when the old source is still active.
(First attempt failed with the laptop at 4K 144 Hz, which USB-C without DSC
may not carry; at 4K 60 Hz it worked.)

The scan sends a real HPD pulse (`0x20` sub 14 (id, 0, 0), (id, 1, …)) to
every HDMI port it visits (`0x260179`, 600 ms): HDMI sources see an unplug
at each scan step (vendor behaviour, not changed).

**No deep standby afterwards** (both sources gone, automatic input):
`fequery.sh`: USB-C code 8 → `0x30`/7 index **0** ("no index"); DP code 7
→ index 8, no source; raw ids 7 and 8 → no source. With USB-C as the
current port the vendor gate sends `0x60`/`0xB` with index 0, gets 0 and
reads it as "source active": standby refused, and with `standby-lhs` the
link-held standby never ends (inference; which port was current is not in
this log). `gate-raw-id` makes the gate send the current port's front-end
id (`0x3B4281[port]`) directly.

## 33. Why the monitor stays in pre-standby: the no-signal repeat (2026-10-08)

**Log** (build before `gate-raw-id`; automatic input, DP output disabled,
USB-C unplugged; LED red): "No signal" (state-4 entry, caller `0x2575C6`)
every 8.04–8.05 s for > 450 s, no port state change, **no standby gate
query** at all. `gate-raw-id` therefore cannot have changed this (and with
it flashed, the monitor still did not reach deep standby).

**Mechanism:**
- The port monitor `sub_23B068` calls `sub_23E64A(port, 2)` (`0x23B2E9`) when
  the port shows no signal (`+0x20 & 0x0C`) and its counter `+0x16` has
  reached `+0x1A`. `sub_23E64A` stores the state (`+0x0C` = 2) and sets path
  state 5 for every path using the port, which re-enters OSD state 4.
- The counter restarts, so the decision repeats every `+0x1A` passes: 400 =
  8 s for DP / USB-C (4 s with `port-nosignal` v1/v2, §24).
- Each state-4 entry sets the countdown `0x4551A6` (`standby-timeout`: 30 s;
  pre-standby 5 s after the entry). The repeat comes after the pre-standby
  (red LED) but long before the countdown ends, so deep standby is never
  requested. The earlier statement in §24 that 400 / 500 passes "leave
  room" was true only for the pre-standby. Same code in stock (countdown
  255 s), so stock is expected to behave the same in this situation
  (inference).

**`nosignal-once`** (untested): the call at `0x23B2E9` goes through a stub
that returns when the port's state is already 2. The first decision of an
episode and every decision after the port has left state 2 are passed on.
Once tested, the DP / USB-C no-signal threshold (8 s) can be shortened
without the loop.

## 34. The no-signal repeat comes from the input path, not the port (2026-10-08)

`nosignal-once` v1 (§33) had no effect on hardware: same 8.04–8.05 s
"No signal" re-entries, no gate query, red LED. Correction of §33:
- After its first no-signal decision the port monitor `sub_23B068` returns
  early on every pass (port flags `+0x1C` bit 1, `0x23B266`); the log shows
  port 1 flags `0x02` from the decision on and no further port state change.
  So the port does not repeat the decision; v1's hook was never reached
  again.
- The repeat is the input-path state machine `sub_22F2C7`: when a path's
  detection round ends while its port shows no signal (`+0x20 & 0x2C`,
  `0x22F692`/`0x22F699`), it calls `sub_26A809` (`0x22F734`) and puts the
  path back into detection (path `+4` = 2). The round takes ~8 s.
- `sub_26A809` derives the OSD state from the signal status. For "no signal"
  it stores state 4 (`0x26A90A`), then clears the OSD timer, sets the
  countdown `0x4551A6` = 0 and runs the state change (`sub_257493`, event
  `0x1E`), whose state-4 entry handler (`sub_26A7C5`) loads the countdown
  again. It does this even when the state is already 4.
- The earlier `port-nosignal` v1/v2 loop (4.07 s with 200 passes) is most
  likely the same path round, whose length follows the port threshold
  (inference).

**`nosignal-once` v2:** the state-4 store in `sub_26A809` goes through a stub;
when the OSD state is already 4 it skips the store and the state change and
continues at `0x26A895` (the normal tail). Every other previous state enters
"No signal" with a fresh countdown as before.

**Test of v2 (2026-10-08, automatic input, DP output disabled, USB-C
unplugged):** one "No signal" entry (51.09 s), panel off 6 s later, and at
81.09 s, exactly 30 s after the entry, the power-save request with the gate
query: refused (1). Link-held standby then re-queried the gate every 5 s
(`0x60` sub `0xFF`, data 8). `fequery.sh` in that state: DP (code 7 and raw
id 8) answered 0 = source active, i.e. the dock kept the DP link up although
the output was disabled; USB-C raw: no source. Before this run the monitor
had restarted (log from ~0 s, scan at 35–51 s): most likely a deep-standby
entry followed by a front-end wake (to be confirmed with `0x453C74` /
`0x453C78`).

## 35. Wake loop with a laptop on USB-C (2026-10-08)

**Observation** (automatic input, DP output disabled, laptop on USB-C with
its output disabled and charging): deep standby is reached, then the monitor
loops: off ~12 s → on ~30 s (laptop picture; KDE on the laptop reports "a new
output has been connected") → "No signal" → off ~27 s → … Every "on" phase is
a fresh firmware start (`logread` saw the event counter drop from 150 to 101
while reading).

**One wake, from the log:** scan USB-C → DP (8.0 s no-signal decision) →
HDMI 1 → HDMI 2 (~1 s each, with the vendor HDMI pulses) → USB-C enable at
24.76 s → USB-C signal 26.85 s, accepted 27.44 s. The laptop sent a picture
2 s after its port was enabled, i.e. its desktop had turned the output on.

**Why the laptop turns its output on:** at every deep-standby wake the
start-up sends each front-end port (id, 0, 0) then (id, 1, 650) (`0x20` sub
14). `wake-no-replug` v3 dropped the low step only for DP, so the laptop saw
an unplug and a re-plug of USB-C, and KDE treated it as a new output and
enabled it. `wake-no-replug` v4 drops the low step for USB-C (id 7) too.

**Still open: what wakes the monitor ~12 s after it went to deep standby.**
Most likely an event-9 wake from the front-end on USB-C activity (the laptop
reacting to the monitor's standby entry); to be confirmed with the wake event
/ port (`0x453C74` / `0x453C78`) and the laptop's kernel log. With automatic
input any connector's activity wakes the monitor (`pm51-input-filter` acts
only with a fixed input). The same pattern was seen earlier with the dock on
DP (§22, automatic input: standby, then a wake shortly after, event 9 port 1).

## 36. Wake loop from the dock on DP, and the standby gate in automatic mode (2026-10-08)

**Tests with `wake-no-replug` v4:**
- Automatic input, DP and USB-C outputs disabled: deep standby quickly, no
  wake for > 2 min.
- Laptop output enabled: immediate wake, picture, other monitor undisturbed
  (wake event 9, port 0 = USB-C).
- Laptop output disabled again (DP still disabled): the loop returns, but
  now with wake event 9, **port 1 = DP**; the laptop's kernel log stays
  empty, so the laptop is not involved any more.

**Reading:** after the USB-C wake the monitor restarted and its start-up /
scan enabled DP again; the dock (MST hub) trained the DP link (no video) and
held it. The vendor gate asks only about the current port (USB-C: no source),
so deep standby was allowed although the DP link was held; the front-end
dropped the link with the standby, the dock retrained it ~12 s later, and the
front-end's event 9 (DP) woke the monitor. In automatic mode the PM51 wakes
on any connector, but the gate only looks at one.

**`gate-all-dp`** (replaces `gate-raw-id`): with automatic input the gate asks
both DP-class connectors (ids 7 and 8, `0x60`/`0xB`) and refuses standby if
either reports an active source; with a fixed input only the selected one
(other connectors' wakes are filtered by `pm51-input-filter`). A failed query
also refuses. Expected: with the dock holding the DP link the monitor stays
in link-held standby (13 W) instead of looping, and goes to deep standby when
the dock releases the link.

**Test of `gate-all-dp` (2026-10-08, automatic input):**
- After flashing: USB-C picture, DP output disabled; laptop output disabled
  → deep standby (laptop still charging), no wake for > 2 min.
- Wake by the menu key: wake event `0x11`, port 0 (`0x453C74` / `0x453C78`;
  key wakes report `0x11`). Afterwards no deep standby: `fequery.sh r7 r8`
  → USB-C no source, DP **source active** (the dock had trained the DP link
  again after the start), so link-held standby, as designed. Disabling and
  toggling the DP output once made the dock release the link
  and the monitor went to deep standby.
- So after every start (wake by key or by USB-C) the dock trains the DP link
  without video and holds it until the PC side changes something; the
  monitor then waits in link-held standby (13 W) instead of looping.

## 37. Speed build (2026-10-08)

**Ports 4 and 5** (port table `0x3B4950`): HDMI-class entries of the reference
design (type `0x20408`, receiver ids 1 and 3, codes 4 and 2 in `0x3B427B`,
front-end id 0 in `0x3B4281`). No connector is behind them, and nothing
selects them: menu input (`+0x4F` 1–4 → ports 0–3), split screen / PIP
second picture (`+0xB2` 0–3 → ports 0–3 on path 1, `sub_2678D9`), the
automatic scan (0 → 1 → 2 → 3) and DDC/CI input select (`sub_26AD19`,
ports 2, 3, 0, 1). Split screen therefore uses the same four ports on a
second input path and is not affected by `hpd-skip-unused`.

**`port-nosignal` v4:** `sub_260E0E` normal-case thresholds: type `0x20`
(USB-C, DP) 400 → 125 passes, HDMI class 500 → 125 (2.5 s each); the flag
case (200) unchanged. Requires `nosignal-once`. Measured enable-to-signal
times: DP after a wake 0.6 s, DP switch 0.2 s, laptop on USB-C after
re-enabling its output 2.1 s.

**`pm51-powerup`:** PM51 power state machine, wake power-up: the delay after
the reg `0x9C` power-good poll (`0x40B7`, `mov r7,#100` → 50) as in GP27U
(`0x5517`) and M27P20P (`0x511C`). The 5 ms between our two reg `0x36` writes
(`0x4078`) stays; GP27U / M27P20P write it only once.

**`hpd-skip-unused`:** `sub_2394DC` skips `0x20` sub 3 for id 0.

## 38. Wake on the waking input first (2026-10-08)

**Log** (build before the speed build; automatic input; wake by enabling the
PC's DP output; 56 events from the start):
- 1.18 s start-up selection `sub_2678D9(0, automatic)` by `sub_268453`: it
  keeps the last input, USB-C (attach 2.26 s).
- 1.43–2.07 s: `0x20` sub 3 for ids 7, 8 and again 7, 8, `0x0B`, `0x0C`, 0, 0,
  66–125 ms each; the two id-0 commands ≈ 0.19 s; `panel-prepower` ready
  2.34 s right after the last one.
- 10.32 s USB-C no-signal decision (8 s), scan to DP: DP signal 0.17 s after
  its attach, accepted 11.15 s. The wake source was DP (event 9, port 1).

**`wake-port-first`:** the start-up call of `sub_2678D9` (`0x2684CA`) goes
through a stub (head zero area `0x201300`): automatic input, wake event 9 and
wake port 0–3 → `sub_23F836(+0x5A, port)` first, then `sub_2678D9` as stock,
which keeps the path's port. In this log the picture would have come ~8.3 s
earlier. Port numbering: PM51 port 0 = USB-C, 1 = DP measured; HDMI (2, 3)
assumed to follow the same table order (not measured).

**No-signal times of other monitors** (normal case, passes of 20 ms): HDMI:
LG 28MQ780 100 (2 s), GP27U 300 (6 s, with type `0x400`) / 200; DP class: LG
100 (2 s), GP27U 200 (4 s); ours (stock) 500 (10 s) / 400 (8 s).

## 39. Hang after a switch to USB-C, front-end failsafe, scan by link status (2026-10-08)

**Speed build results** (§37/§38 list with `pm51-powerup`, `wake-port-first`):
- Automatic input, DP output disabled, laptop active on USB-C: USB-C picture
  after ~6.8 s. USB-C output disabled, DP active: DP picture after ~4.2 s.
- Input fixed to DP, wake from deep standby: picture after ~6.2 s, no
  "No signal".

**Incident** (same build; input fixed to DP; DisplayPort Mode "1.4 without
DSC"; laptop on USB-C with its output enabled):
- In deep standby the laptop on USB-C did not wake the monitor
  (`pm51-input-filter`, as designed).
- Wake by the menu key, then USB-C selected in the menu: the screen stayed
  black. Some time later the keys stopped responding and DDC/CI did not answer
  (`poke.sh`, 30 tries). "No signal" appeared, then the red LED with the panel
  still on, panel off ~4 s later. Then (by the owner's reading) link-held
  standby, DDC/CI still dead.
- After a mains cycle the input was DP again: the USB-C selection had not been
  saved. No log could be read.

**Common factors with §30** (none proven as the cause):
- Input fixed to DP with the laptop connected to USB-C, a deep-standby wake,
  then no picture from the front-end and no DDC/CI, while the firmware still
  acted on its own.
- Both builds had `wake-no-replug`, `pm51-input-filter` and a change of the
  selection's HPD command (`select-no-replug` / `switch-no-unplug`).
  `pm51-powerup` was only in the second one; it is left out of builds until
  this is explained.
- In §30 the keys kept working while DDC/CI failed, so DDC/CI can fail while
  the main loop runs. Its path from the USB hub (VL822 I2C) to the scaler is not
  traced. If it passes through the front-end, or a bus the front-end shares, a
  front-end that has stopped working explains the DDC/CI failure in both
  incidents (inference).

**Reading (inference):** keys that stop responding mean a blocked main loop.
The only long waits on that path are front-end mailbox transactions (§22):
- up to 10 s per phase;
- a posted command waits in phase 1 while the PM51 still retries the previous
  one (5 tries with 100 ms pauses plus its own answer time-out, `0x8A5E`ff);
- a query waits up to 30 s.

In link-held standby the gate query runs every 5 s, and `gate-all-dp` refuses
standby when it gets no answer, so the monitor stays there with the main loop
mostly blocked.
- `mailbox_query` is identical in GP27U (`0x23BA85`) and M27P20P (`0x23C3FD`):
  three 10 s waits, no failure handling.
- No front-end reset or recovery was found in any of the three firmwares.

**`fe-failsafe`** (untested):
- The three wait loads in `mailbox_query` (`0x238FD9`, `0x239091`, `0x23914B`)
  call a stub. It returns 10000 ms, or 500 ms while the flag at RAM `0x2024E0`
  is set.
- The function's last instructions (`0x239023`) jump to an exit stub, after the
  epilogue `diag-log-ring` hooks at `0x239002`. The exit stub reads the wait
  counter `0x4551C8`: 0 means a phase ran out (this also catches a posted
  command whose phase 2 ran out, which returns 1). It then sets the flag and
  counts the failure at `0x2024E1`, up to 255; any completed transaction clears
  the flag.
- Normal operation is unchanged until one transaction has run out its full
  10 s. Every start begins with the flag clear (the image head is copied from
  flash).
- While the flag is set, a command that the PM51 would only take after more
  than 0.5 s is dropped instead of sent late.
- Expected effect: keys and OSD keep working while the front-end does not
  answer, and DDC/CI too if its own path still works. `0x2024E0`/`0x2024E1` and
  the "K MAILBOX FAILED" entries of `diag-log-ring` show whether the front-end
  stopped answering.

**Test to find the trigger:**
1. Repeat the steps (fixed DP, laptop active on USB-C, deep standby, key
   wake, select USB-C) with `fe-failsafe` and `diag-log-ring`.
2. If it hangs, read `0x2024E0`/`0x2024E1` and the log.
3. If the hang is reproducible, repeat without `pm51-input-filter`, then
   without `wake-no-replug`.

**Reference firmwares, re-checked:**
- GP27U and M27P20P send the link query `0x60`/`0xB` only from their standby
  gate (GP27U `0x26BAD6`, M27P20P `0x26AEFB`), as ours does. Their scans do not
  ask the front-end.
- GP27U reads the PM wake port at start-up (`0x26B350`, debug string
  `ePMWakeupActivePort`). It logs the port, starts on the last input as ours
  does, and sets a byte (`0x502249`) when the two differ. That byte later
  selects power-on state 8 instead of 6 (`0x45068C`, `0x27A78A`); what state 8
  does was not traced. So no reference firmware starts on the wake port
  (`wake-port-first`).

**`scan-active-first`** (untested, requires `fe-failsafe`): the scan step
(`0x2601EB`, `jal sub_2653EA`) goes through a stub.
1. **Query:** for the next three inputs in rotation order, the stub asks the
   front-end about each DP-class input (`0x60`/`0xB` with its front-end id).
   HDMI inputs are not asked.
2. **Jump:** once per search, it takes the first input that reports an active
   source, even if HDMI inputs come before it. Example: DP lost, laptop active
   on USB-C → USB-C directly, ~2 s less than the measured 6.8 s.
3. **Skip:** otherwise it follows the stock rotation, but skips a DP-class
   input that reports no source (2.5 s each).
4. **Fallback:** a query without an answer ends the step with the stock
   `sub_2653EA`.

After a jump, the next jump waits until a signal has been accepted on any
port (accept counter of `picture-watchdog`, §40; RAM `0x2024E8` = jumped,
`0x2024E9` = the counter at the jump). If two DP-class connectors both hold a
link without video (e.g. an MST dock), the scan therefore still visits the HDMI
inputs. Key-selection mode (`0x4551AC` bit 5) is stock. (The first version
cleared the flag at `sub_23E64A(port, 1)`, `0x23B367`, which is a detection
restart, not an accept, §40; corrected before any hardware test.)

Limitation (stock, §32): in "1.4 without DSC" the scan's attach sends no
"HPD high" to the new connector; if the old connector's source still holds its
link, the front-end may keep showing the old picture.

## 40. Black screen without "No signal": detection restarts, `picture-watchdog` (2026-10-08)

**Test results** (build of §39 without `pm51-powerup`):
- Input fixed to DP, USB-C active: the wake from deep standby worked.
- "No signal" appears noticeably faster (`port-nosignal` v4).

**Incident** (input fixed to DP, after a start): black screen with the
backlight on and no "No signal" message, for ~45 min. Keys and DDC/CI worked.
`diag-log-ring` (the start of the episode is not in the 64-entry ring):
- Port 1 (DP) cycled without end:
  - no-signal decision (state 2, flags `0x22`);
  - 0.2–7 s later a short signal (status `0x03` for 2–10 ms, then `0x0F`) made
    the port monitor restart detection (state 1, flags `0x20`);
  - 4–6 s later the next no-signal decision.
- The port never reached state 3. No input selection and no mailbox commands
  in that time.
- Opening the menu showed the reduced menu (no video). At menu close the vendor
  retry ran (`sub_258E5D` → `sub_2678D9(0, DP)`):
  - `0x20` sub 0 (0, 8) (disable), `0x60` sub 6, `0x20` sub 14 (8, 1, 0);
  - 0.2 s later the attach: (8, 1), `0x60` sub 2 (8, 1), `0x20` sub 0 (1, 8);
  - DP status `0x13`/`0x03` at once, state 3 0.6 s later
    (`port-accept`), then state 4 and the picture.
- DisplayPort Mode was 1.4 (DSC) in this run (`0x60` sub 2 in the attach).

**Port states** (`sub_23E64A(port, state)`, from `sub_23B068` and `sub_241D2B`;
§17 has the same):

| State | Set by | Meaning |
|---|---|---|
| 1 | `0x23B367` | detection restarted after a change (flags bit 0); path state 1 |
| 1 | `0x241DC2` | the mode set after an accept failed (`sub_2417B9`); path state 1 |
| 2 | `0x23B2E9` | no-signal decision (+0x1A passes); path state 5 |
| 3 | `0x23B33B` | signal accepted (stable for +0x18 passes); path state 1 |
| 4 | `0x241D91`/`0x241DCA` | mode set (`sub_241D2B`); path state 2 |

**Reading:**
- The scaler's DP receiver got no stable signal from the front-end, only
  blips.
- Each blip restarted the port's detection and with it the input path's
  detection round. So the round never ended with "no signal": no "No signal",
  no countdown, no standby.
- A new selection (front-end port disable / enable with the switch trigger)
  brought a stable signal at once.
- Why the front-end output was unstable is not known. Candidates:
  - Our start-up without any HPD-low step for DP (`wake-no-replug` with
    `switch-no-unplug`): the stock start forces the source to retrain the link
    with a 650 ms unplug. The PC log of 2026-10-07 (§16) shows the front-end
    sending short pulses (IRQ_HPD) on its own after a wake.
  - A front-end problem unrelated to the patches.
- §30 (black screen without "No signal" after a wake, keys working) fits the
  same pattern. There the menu retry sent no HPD command (`select-no-replug`),
  which would explain why it did not recover (inference).

**`picture-watchdog`** (untested; code at `0x201800`, RAM `0x2024D0`–`D3`):
- **Counting:**
  - `0x23B367` (restart) counts restarts of the main path's port (path 0 record
    +0x28, `0x4821D4`) at `0x2024D1`;
  - `0x23B33B` (accept) clears the count and counts accepts of all ports at
    `0x2024D0` (used by `scan-active-first`);
  - a different port in path 0 starts the count over;
  - restarts after a failed mode set (`0x241DC2`) come after an accept, so they
    do not add up.
- **Action:** the main loop (`0x26214F`, before `sub_260ACF`, next to the OSD
  task that runs the vendor retry) checks the count on every pass. At 3
  restarts without an accept, outside power-save (`0x4551AC` bit 0; in
  power-save the count is cleared):
  - recovery 1: `sub_2678D9(0, settings +0x4F)`, the same call as the
    start-up selection and the menu retry;
  - recovery 2 (if the restarts continue): `sub_23EE83(port, 650)`, the vendor
    hot-plug pulse (the source sees a ~0.7 s unplug, as at every stock wake),
    then the selection again. `PULSE=0` in the generator leaves this step out.
  - After that nothing more until a signal is accepted. `0x2024D2` counts the
    recoveries.
- **Expected effect** for the incident above: picture after about 3 restart
  cycles (~15 s) instead of never.
- **Not affected:** an input without a source stays in state 2 without
  restarts. An input whose source keeps its link without video (MST dock)
  showed no restarts in §34.

**Diagnosis aid:** `tools/logread.py` names the watchdog's selections
("picture-watchdog recovery") and those of `wake-port-first`.

## 41. No wake from USB-C in link-held standby (2026-10-08)

**Test** (build of §40):
- Several manual switches DP ↔ USB-C worked.
- Automatic input, DP and USB-C outputs disabled → standby. Enabling the
  laptop's USB-C output did not wake the monitor; the picture came only after
  6+ min.

**Log:**
- From 193 s to 618 s only the standby gate's re-query every 5 s
  (`0x60`/`0xB` for ids 7 and 8). So the monitor was in link-held standby, not
  deep standby; the firmware did not restart. Most likely the dock held the DP
  link, as in §36.
- At 631.6 s link-held standby ended (cause not in the log). The scan went
  DP → HDMI 1 (no signal 1 s later) → HDMI 2 → USB-C; USB-C accepted at
  635.9 s.
- `scan-active-first` did not jump to USB-C. Its last jump was before standby,
  and no signal had been accepted since, so its guard held.

**Reading:**
- In link-held standby only the current input's own signal ends it
  (`standby-lhs` `cave_b`), and the front-end routes only the current
  connector. The PM51's source wake (event 9) works only in deep standby.
- So with automatic input, a source on the other connector cannot wake the
  monitor while a held link (the dock) keeps it in link-held standby. Stock is
  the same, except that its gate asks about the current port only.

**`gate-all-dp` v3:**
- The gate keeps each connector's last answer (RAM `0x2024C0` USB-C,
  `0x2024C1` DP).
- When a connector that is not the current one changes from "no source" to
  "source active" during link-held standby (rws `0x4551CC` set):
  - the gate clears rws and calls `sub_245919`, as `standby-lhs`'s key exit
    does;
  - it refuses standby;
  - the automatic scan then finds the source.
- A link that stays active (the dock) cannot wake the monitor, because only a
  change counts.
- Every gate call also clears `scan-active-first`'s jump flag, so the search
  after a standby decision may jump again.
- The code moved to the image head zero area (gate `0x201900`, query
  `0x201280`). The query now tells "no answer" apart from "source active"; both
  still refuse standby, as in v2.
- Expected wake time: the next re-query (≤ 5 s), then the scan's jump to USB-C
  and the laptop's picture (~2–3 s).

## 42. USB-C wake test; `picture-watchdog` v2 (2026-10-08)

**Test** (build of §41, automatic input; standby on DP, then the laptop's
USB-C output enabled):
- Deep standby was reached; the wake by USB-C worked (firmware restart).
- `wake-port-first` started on USB-C (selection at 6.48 s, "by
  wake-port-first").
- USB-C accepted at 8.32 s, backlight at 8.38 s.
- No HPD-low command went to USB-C, only "HPD high" (7, 1), `0x60` sub 2
  (7, 1) and the enable. The owner saw something like a re-plug on the laptop.
  The laptop's own output being enabled, or USB-C alternate mode set-up after
  deep standby, would look the same; this was not decided. The laptop
  (new, Debian) is not treated as a reference.

**`picture-watchdog` v1 fired falsely:** recovery 1 ran at 7.65 s, 1.05 s
after the main loop started.
- During a normal signal acquisition the port restarts detection several
  times within ~1 s. The log shows only state changes, so the repeats of state
  1 are not visible.
- The recovery was harmless here (`0x60` sub 6, "HPD high"; picture
  0.7 s later), but it is not what the watchdog is for.
- v2 counts a restart only if a no-signal decision (`0x23B2E9`, hooked; RAM
  `0x2024D4`) came since the last counted one. That matches the black-screen
  pattern of §40 (no signal → blip → restart → no signal …) and excludes the
  acquisition after an attach.

**Open: 5 s gap in the start-up.**
- After the front-end set-up (config update end 1.45 s) nothing was logged
  until the start-up selection at 6.48 s, and the main loop started at
  6.60 s; earlier wakes started their main loop at ~2.1 s (§16, §38).
- `diag-log-ring` does not log `0x20` sub 18, and a mailbox wait of ~5 s
  (PM51 busy, under the 10 s time-out, so no "K" entry) would fit. The cause
  is not known.
- A log of a DP wake with this build would show whether the gap belongs to
  USB-C wakes.

## 43. DP wake timing; link-held standby routing (`gate-all-dp` v4) (2026-10-08)

**DP wake** (build of §42, automatic input, wake by DP):
- start-up selection 1.57 s ("by wake-port-first", DP);
- main loop 1.69 s;
- DP accepted 3.38 s, backlight 3.46 s.

The 5 s gap of §42 is therefore specific to the USB-C wake (cause still
open).

**Not reproduced** (2026-10-09, build `diag_v17`, DP cable unplugged, laptop
USB-C output disabled → deep standby, then enabled; stopwatch enable →
picture ~6.7 s): main init 0.11 s, start-up selection 1.53 s ("by
wake-port-first", USB-C), main loop 1.65 s, port enable (`0x20` sub 0) 2.04
s, signal 2.71 s (one short no-signal reading 2.75 s), accepted 3.37 s,
backlight 3.43 s. Same as the DP wake above (3.38/3.46 s). The ~3.3 s
before the firmware clock starts (laptop output enable, front-end activity
detection, PM51 wake, power-up and boot loader) matches the ~2.6 s of §18
plus the laptop's own enable time; not split further. The §42 gap is not
explained; it did not occur in this wake.

**`gate-all-dp` v3 did not help** (automatic input; DP output disabled, the dock
held the DP link; the laptop's USB-C output enabled ~3 s after "No signal"
disappeared):
- The scan had last moved to HDMI 2 (426.4 s), "No signal" at 427.5 s, panel
  off 433.5 s. The laptop was enabled before the gate's first query (the
  power-save request 30 s after "No signal").
- Link-held standby re-queried both connectors every 5 s (527 s …); the
  picture came only minutes later.
- v3 woke only on a "no source" → "source active" change it had seen, so an
  already active laptop never counted. With HDMI 2 routed, no video could end
  link-held standby.
- The vendor scan stops stepping after its first round (`sub_25FE39`: after
  the per-call counter passes its limit it only handles "no signal"), so
  during the 30 s before standby nothing moved either (inference from the code
  and this log).

**v4: route instead of wake.** While in link-held standby with automatic input,
each re-query routes path 0 (`sub_23F836(0, port)`, as the scan; status
"no signal" until the port reports one; panel stays off) to:
1. a connector other than the current one whose answer changed to "source
   active";
2. else, if the current input is HDMI or its connector has no link: the
   first other connector with an active link;
3. else (both links active): the other connector every 6 re-queries
   (30 s; `ALT`), so video on either is found while two links are held.

The routed connector's video then ends link-held standby the normal way
(`standby-lhs` `cave_b`, relight on valid timing). Expected for the test
above: ≤ 5 s after the first re-query, USB-C routed → laptop picture.

Code: gate `0x2016D0`, link-held part `0x201900`, query `0x201280`.

Open: whether routing changes every 30 s while two links are held disturb a
source (each change is the same as a manual switch, which did not disturb
the PCs in §31/§32).

## 44. DisplayPort Mode re-selected; standby timing; routing during "No signal" (2026-10-08)

**DisplayPort Mode re-selected (1.4 → 1.4)**, monitor showing DP:
- Both monitors behind the dock blanked. The main one came back; this one
  restarted detection on DP (1323.19 s), decided "no signal" 2.48 s later,
  showed "No signal" and turned the panel off 6 s after that.
- The OSD action `0x268C20` stores the menu value into `+0xCB` and always
  calls `sub_268BB0` (650 ms hot-plug pulse on DP and USB-C, port
  configuration, `0x60` sub 2 / sub 0). The pulse makes the dock's MST
  topology change, which blanks all its monitors.
- The input was fixed to DP (owner, after the report). With a fixed input a
  later signal restarts detection and is accepted (also in link-held standby,
  and a DP source wakes deep standby), so either the PC sent no video to this
  monitor again, or the monitor did not accept what came (as in §40, where
  the front-end delivered only short blips). The `-n 10` read shows neither;
  15 events that arrived while it was read are not shown.
- Why the PC did not send video to this monitor again is not in the log. The
  PC re-creates the connector after such a pulse and needed ~5 s in §29, so
  the 2.5 s no-signal time (`port-nosignal` v4) expires first. With the input
  fixed, a later signal still restarts detection and is accepted. With
  automatic input, the vendor scan has moved away by then; `gate-all-dp` v4
  routes back to a connector with an active link.
- **`dpmode-same`:** the action skips the store and the apply when the value
  equals the current `+0xCB` (writers of `+0xCB`: defaults, profile restore,
  this action, so the comparison sees the old value). A real change is
  applied as stock.

**Standby timing** (with `standby-timeout`; owner's question): "No signal"
starts the countdown `cnt` (30 s).
- After ~5 s the vendor pre-standby turns the panel off with the red LED (the
  log shows 6 s).
- At 0 the power-save request runs the standby gate: deep standby if no link
  is held, link-held standby if one is.
- Pre-standby and link-held standby look the same from outside (dark panel,
  red LED). Before v4 the gate and its 5 s re-query, and with them the
  routing, ran only from the 30 s point.

**`gate-all-dp` v4 addition:** the 1 s task's countdown step (`0x261CEB`,
`sub_261C04`) calls the gate every 5 s while the OSD state is 4 ("No signal"
and pre-standby).
- A flag (`0x2024C4`) lets the gate route there although link-held standby
  is not set; the result of the gate is ignored there.
- A laptop enabled during the countdown is found within ~5 s instead of
  after 30 s + 5 s.

## 45. DisplayPort Mode apply leaves the input disabled (stock bug) (2026-10-08)

**Log** (build of §43, input fixed to DP, DisplayPort Mode 1.4 re-selected):

| Time | Event |
|---|---|
| 462.318 | `0x20` sub 14 (8, 0) / (8, 1): the 650 ms pulse |
| 462.323 | `0x20` sub 0 **(0, 8)**: DP disabled |
| 462.328 | `0x60` sub 2 (8, 1) |
| 462.335–462.354 | the same for USB-C (7) |
| 462.360 | `0x60` sub 0 (8, 3) |
| 462.92 | port 1 restarts detection |
| 465.40 | no-signal decision; "No signal", panel off 6 s later |
| 530 s on | link-held standby: the gate asks DP every 5 s (the dock held the link) |

No enable for DP was sent at any point.

**Code:**
- `sub_26535A(port, dsc)` (called by `sub_268BB0` for ports 1 and 0):
  - `+0xA5` = dsc;
  - `sub_23EE83(port, 650)`;
  - `sub_23959E(0, id, …)`, i.e. `0x20` sub 0 with enable = 0;
  - `sub_239333(id, dsc)`, i.e. `0x60` sub 2;
  - then a tail call to `sub_264633(dsc)`.
- Only `sub_264633` requests the port configuration update that enables the
  input again (`0x264683`: path 0's port entry in `0x3B4288`, +0 = 1,
  +0x11 = 0, +1 = 2). It does that only when dsc differs from its cache
  `0x455061` (or settings `+0x59` ≠ 0).
- So in stock, re-selecting the current mode, and changing between "1.4
  without DSC" and 1.2 (dsc 0 both), leave the selected input disabled in the
  front-end: "No signal" until another input selection or a restart. §29's
  "1.2 gave No signal until a restart by the power key" fits.

**`dpmode-same` v2:**
- An unchanged value does nothing (no pulse, no disable).
- A change is applied as stock and is followed by the same update request for
  path 0's port, so the input is enabled again (with `switch-no-unplug`:
  "HPD high", `0x60` sub 2, enable).
- The other DP-class input stays disabled until it is selected, which enables
  it (as in stock).

**Test of v2 (2026-10-08, input fixed to DP):**
- Re-selecting the current mode: nothing happens (the menu cursor jumps back
  to the selected entry).
- 1.4 → "1.4 without DSC": picture back.
- "1.4 without DSC" → 1.2: "No signal", panel off, then link-held standby
  (fixed input: the gate asks DP every 5 s; the dock holds the link).
  - The apply ran as in stock, ending with `0x60` sub 0 (8, 1).
  - v2's update request then ran: 40.177 `0x20` sub 0 (0, 8), DP restart,
    40.191 `0x20` sub 0 **(1, 8)** (enable).
  - DP no-signal decision 2.47 s later.
- So the input is enabled now, but in 1.2 no video arrives although the link
  is up (gate: source active). §29 saw the same with 1.2 in an earlier build
  ("No signal" until a power-key restart).
- Open, not decided: whether the PC / MST dock sends no stream after the
  change to HBR2 without DSC (e.g. the desktop mode does not fit and is not
  changed), or whether the front-end needs the start-up initialisation for
  the new link rate (only the start-up sets everything up after
  `0x60` sub 0).

**Resolved (2026-10-08):** with the PC set to 4K 60 Hz the 1.2 picture came at
once, and 1.4 → "1.4 without DSC" → 1.2 → 1.4 worked at every step. The
earlier 1.2 failure was bandwidth: the PC's 4K 144 Hz mode does not fit HBR2
without DSC, and the PC kept the link without sending a stream. Not a
firmware problem; `dpmode-same` is hardware-tested.

## 46. Stuck without "No signal" after the scan (automatic input) (2026-10-08)

**Test** (`gate-all-dp` v4, automatic input):
- DP output disabled (the dock holds the link), then the laptop's USB-C output
  enabled during the countdown: the monitor woke and showed the laptop. The
  5 s routing check during "No signal" works.
- Laptop output disabled again: black screen, panel on, no standby.

**Log:**
- 358.3 s scan to HDMI 1, 359.36 s its no-signal decision.
- 359.38 s `scan-active-first` asked USB-C and DP. The jump flag was set, so
  it continued in rotation to HDMI 2.
- 360.45 s HDMI 2 no-signal decision. After that, nothing until the owner's
  `fequery` calls (590–656 s) and a new scan round at 985 s (cause not in
  the log).
- No standby-gate tick in ~625 s, so the countdown `cnt` was not running.
  No OSD state change and no "No signal" entry in the window either.
- `fequery` in that state: USB-C no source, DP source active (the dock), the
  routed connector HDMI 2.
- The link query answered 0 for HDMI 2's id (`0x0C`) with nothing connected,
  so for HDMI ids the answer does not mean "source active". No patch uses it
  for HDMI.

**Candidate (not confirmed): the vendor's countdown pause.**
- `sub_263995` sets `0x453C70` bit 15 and the re-evaluation timer `0x4551B5`
  = 10 on a DP link event of the current port during "No signal"
  (`0x263C26`).
- The countdown does not run while bit 15 is set (`0x261CDA`).
- Bit 15 (with bit 14) is cleared only when `0x45792D` = 9 (`0x263AA8`,
  `0x26B23B`), i.e. never without a signal. The bit-14 path re-enters
  "No signal" through state `0x0D`; the bit-15-only path was not traced to a
  re-entry.
- To be confirmed by reading `0x453C71` (bit 7 = bit 15) in the stuck state.

**Log fix:** the `diag-log-ring` watcher read `0x453C72` as "bits 15–8" of
`0x453C70`. This CPU is little-endian (`0x261CDA` tests bit 15 as
`0x453C71` bit 7), so it watched bits 23–16, and bit-15 changes were never
logged. It now watches `0x453C71`.

## 47. The stuck state is not the countdown pause; `0x453C70` bit 16 (2026-10-08)

**Reading in the stuck state of §46:** `0x453C71` = `0x00` (bit 15 clear),
`0x453C70` = `0x50`.
- Bit 6 is the countdown task's 1 s flag.
- Bit 4 is set by `key_process` (`0x257FFB`), `sub_23ADAF` (`0x23AFBB`) and
  `0x23FFB0`.
- The countdown pause of §46 is ruled out.

**The countdown never started:**
- `sub_261C04` reaches the `cnt` step every second (also through the
  re-evaluation and menu-timer branches, `0x261DC9` → `0x261CCB`).
- With bit 15 clear, a stopped countdown means `cnt` = 0, i.e. "No signal"
  (state 4, whose entry handler loads `cnt`) was never entered in this
  episode.

**Candidate: `0x453C70` bit 16.** The scan handler's no-signal branch
(`sub_25FE39`, `0x2600DF`) returns without calling `sub_26A809` while bit
16 is set.
- Bit 16 is set by `key_process` (`0x257E34`, `0x257E93`).
- It is cleared by `sub_258E5D` at the menu-timer end (`0x2590B0`, the
  vendor retry path of §29) and by `power_soft_off`.
- The earlier `diag-log-ring` watcher on `0x453C72` (bits 23–16) did show
  this bit: in §40 it went to `0x00` exactly at the menu-close retry. It is
  watched again, next to `0x453C71`.
- To be confirmed by reading `0x453C72` (bit 0) in the stuck state.

## 48. Recovery from the stuck state; `+0x5B` not updated by the routing (2026-10-08)

**Log of the same run** (monitor still on the earlier `diag-log-ring`,
which watches `0x453C72`; decoded with the newer patch file, its entries
appear as "0x453C71", because a watch entry was inserted before it):
- Another stuck episode: scan DP → HDMI 1 (1613.6) → HDMI 2 (1614.7),
  HDMI 2 no-signal 1615.86 s, then nothing for 354 s.
- 1969.73 s: menu key; OSD state 8 (quick input menu), `0x453C72` 0x00 →
  0x01 (bit 16 set). So bit 16 was 0 during the stuck period (the watcher
  logs changes only): bit 16 is ruled out as well.
- 1973.53 s: the menu-timer retry (`sub_258E5D`): `sub_2678D9(0, automatic)`;
  OSD state 6; bit 16 cleared.
- HDMI 2 no-signal 1974.75 s, **"No signal" entered 1974.85 s**.
- 1979.85 s: the routing tick (5 s), DP active (the owner had re-enabled DP)
  → routed to DP; DP accepted 1980.64 s.

**Finding in our patch:**
- settings `+0x5B` holds path 0's current port. It is written by the scan
  (`0x260189`), by `sub_2678D9` (`0x2679A8`) and by `sub_26A809`
  (`0x26A9BC`), and read by `sub_26A809`, the OSD, DDC/CI and many others.
- The v4 routing called `sub_23F836` without updating it, so after a routing
  (e.g. the earlier laptop wake in this run) `+0x5B` named the old port.
  Whether that caused the missing "No signal" decision is not proven, but it
  is an inconsistency the vendor scan never creates.
- v4.1 stores the port in `+0x5B` as the scan does. The tick moved to
  `0x201350` (room).

The cause of the missing "No signal" remains open. The next test with the
current build (both flag bytes watched, `+0x5B` consistent) should show
whether it recurs.

**Test of v4.1 (2026-10-08, automatic input, DP output disabled):**
- Laptop enabled during the countdown → laptop picture.
- Laptop disabled → "No signal", then deep standby (the dock had released
  DP this time).

**Log decoding check:** `diag-log*` builds now carry a one-byte signature at
`0x202414` (CRC of mode, watch list, tags and code; a constant in the image
head, so it needs no code). `tools/logread.py` reads it first and warns when
it differs from the patch file, as happened in §48 (old build, newer patch
file: watch labels shifted by one).

## 49. Stuck state explained: a detection restart clears the countdown, `nosignal-once` v3 (2026-10-08)

**Test** (build of §48, automatic input, DP and USB-C outputs disabled, deep
standby, laptop charging): unplugging and plugging the laptop woke the
monitor (event 9, port 0). Result: black screen, panel on, nothing
displayed.

**Log:**
- Scan DP (22.45) → HDMI 1 → HDMI 2, HDMI 2 no-signal 27.11 s, "No signal"
  27.23 s (OSD state 4).
- 32.23 s: the routing tick (USB-C no source, DP active), routed to DP
  (32.27 s: port 1 state 1).
- 34.77 s: DP no-signal decision. Then nothing: no tick, no "No signal"
  entry, OSD state unchanged.
- Readings: `0x453C71` = 0, `0x453C72` = 0, watchdog counts 0; `fequery`:
  USB-C no source, DP source active.
- (The first query at 32.23 s is logged with id `0x00`. The built code reads
  `07` from `0x3B4281` and the scan's queries in the same log show `0x07`, so
  this is most likely a byte read error of the log read.)

**Cause:**
- Every detection restart of a port (`0x23B367`, `sub_23E64A(port, 1)`, tail
  call `sub_23AB33`) clears the power-save request bit and the countdown
  (`0x23AB7A`–`0x23AB91`: `0x4551AC` &= ~2, `cnt` = 0).
- Stock relies on the next "no signal" decision re-entering state 4, which
  reloads `cnt`. `nosignal-once` v2 skipped that re-entry whenever the OSD
  state was already 4.
- So after any restart during "No signal" (the scan attaching the next port,
  or `gate-all-dp`'s routing) the countdown stayed 0: no pre-standby, no
  standby, no routing tick (it runs on the countdown). It stayed so until
  something else happened (a key, the menu retry, a new scan round).
- This explains the stuck runs of §46–§48. It is also why it appeared only
  together with the scan/routing after "No signal": in §43, "No signal" came
  after the last scan step.

**`nosignal-once` v3** (cave moved to `0x203B80`): when the OSD state is
already 4, the re-entry is skipped only while the countdown runs (`cnt` ≠
0), or link-held standby is set (rws), or power-save is requested (`0x4551AC`
bit 1). Otherwise "No signal" is entered again as stock and reloads `cnt`.
- Expected: after a restart during "No signal", one more "No signal" entry
  (the message may show again) and a fresh 30 s countdown, then standby as
  usual.
- Link-held standby and a pending standby are unaffected. The repeated 8 s
  rounds of §33 still do not restart a running countdown.

**Test of `nosignal-once` v3 (2026-10-08):** automatic input, DP and laptop
outputs disabled, deep standby (laptop charging on USB-C). After unplugging
and replugging USB-C: wake, "No signal", nothing shown, "No signal" again,
then pre-standby. This is the expected sequence (§49); the stuck state of
§46–§48 did not occur. Not checked yet: whether deep standby followed.

## 50. Half-width DP picture after a start (one occurrence) (2026-10-08)

**Observation:** first mains start after flashing the build with
`nosignal-once` v3 (automatic input, PC on DP at 3840×2160 144 Hz with DSC,
laptop output on USB-C disabled). The picture showed the left half of the
PC's image stretched to full width; top and bottom complete, OSD normal. OSD
information: "1920x2160@144Hz" (normal: "3840x2160@144Hz"). The PC reported
3840×2160 at 143.98 Hz throughout.

**Log** (`diag-log-ring`, last 64 of 93 events): scan HDMI 1 → HDMI 2 → DP.
- At 6.96 s the DP link query most likely answered "no source": the PC was
  still training the link after the monitor start, so `scan-active-first`
  did not jump. The answers are not logged.
- At 8.04 s DP was active and was attached; accepted at 8.85 s.
- The DP attach (port 1 flags `0x20 → 0x26 → 0x2E → 0x2A`, status `0x03 →
  0x43`, state 3 → 4, `0x60` sub 2 DP = 1) matches all earlier DP attaches.
- No further events after 14.8 s. The fault was most likely there from the
  first picture.

**Recovery:** setting the PC to 120 Hz gave a correct picture; back to 144 Hz
stayed correct ("3840x2160@144Hz"). A new timing detection and mode set
clears it.

**Not established:**
- How a 4K 144 Hz input reaches the scaler. The width checks at 1920
  (`sub_22284B`: path window +0x18/+0x1C → +0x35/+0x36) concern the output
  halves of the panel, not the input.
- Lead: in the DP wake log of §43 port 0 (USB-C receiver)
  ran detection and acceptance together with port 1. Here no port 0 event is
  among the kept entries; in another correct start it was absent as well,
  so this proves nothing.
- Whether stock firmware shows this too. No patch in the build writes scaler
  or timing-measurement registers; they change when and in which order
  inputs are selected.

If it recurs: read `tools/logread.py` and the OSD information before
changing anything; next step would be watching port 0 and input path 1
(`0x47FAE0`) in `diag-log-ring`.

**Second occurrence** (2026-10-09, build `diag_v17`, main CRC `263009a3`,
again the first start after flashing; OSD "1920x2160@144Hz"; read while the
fault was on screen, then again after the 120 → 144 Hz recovery):
- Log: same sequence as above (HDMI 1 → HDMI 2 → DP, DP attached 8.07 s,
  port 1 state 4 at 8.84 s, nothing after 14.8 s). It does not separate the
  fault from a correct start.
- Front-end MSA (`fereg.sh preset msa`): identical in fault and after
  recovery. Only decoder 1 carries a stream: 3840 × 2160, htotal 4000,
  vtotal 2222. The front-end receives the full-width stream as one SST
  stream. The half width arises after the decoder (front-end output to the
  scaler, or the scaler's input set-up).
- Link: lane status `0x77`, `0x110D32` = `0x14`. `fequery`: DP source
  active.
- DPCD bank `0x1200` compared with the §54 "with picture" file (another
  session, after a wake): `0x1240`–`0x125F` is an exact copy of
  `0x1220`–`0x123F` in the fault, but different in the §54 file; further
  `0x121E`/`0x121F`, `0x1226`, `0x1235`, `0x15E5`. Not yet compared with a
  correct state from the same session; meaning of the block unknown.
- PC (amdgpu debugfs, fault state): `dsc_pic_width` 1920, `dsc_pic_height`
  2160, `dsc_slice_width` 960, `dsc_slice_height` 108, `dsc_bits_per_pixel`
  146 (9.125 bpp), link 4 × HBR3 (on the PC's side of the USB4 dock). 1920
  is probably the width per DSC engine with the GPU's 2:1 pipe combining at
  this pixel clock (the PPS sent to the monitor would then carry 3840).
  After recovery it also reads 1920: the PC sends the same in both states.
- Start conditions of both occurrences: mains start, the first after a
  flash; the PC was sending video during the flash.
- Same-session correct state (`dp_ok`, after recovery): `0x1240`–`0x125F`
  reads `02 00 01 00 10 00 00 … 07 07 00 00 01 10 0B 00 … 01 00 00 00`,
  identical to the §54 picture and link-held files. Only the fault differs
  (exact copy of `0x1220`–`0x123F`). The other differences (`0x121E`,
  `0x1226`, `0x1234`–`0x123A`, `0x15E0`/`0x15E5`) also vary between correct
  states. The front-end code touches this block only with single-bit
  writes (`0x1242` bit 0: `0x4D2C7`, `0x5702E`; `0x1254` bit 0: `0x57118`;
  `0x1256` bits 0–3: `0x4F68F`); a whole-block copy is not explained by
  them. A read artefact is not excluded: the firmware writes every buffer
  byte (0 on a failed read) and a lost address SET would read zeros, not
  the neighbouring block, but the front-end's own read path was not
  checked. Meaning of the block unknown.

**Plan** (owner, 2026-10-09): never seen with stock firmware, so a patch
(or the order of input selection it causes) is the most likely trigger;
first seen with the `nosignal-once` v3 build. At the next occurrence:
`tools/fereg.sh 0x001220 32 0x001240 32 0x001238 16 0x001248 16`, twice,
to confirm the block copy is real. Kept in reserve: a recovery that compares
the scaler's measured width with the front-end MSA width after a DP accept
and re-runs timing detection on a mismatch (no hot-plug pulse).

## 51. Link-held standby power: where the 13 W go (2026-10-08)

**Wake reason after the DP toggle of the §49 test:** `0x453C74` = 9,
`0x453C78` = 2, with nothing connected to HDMI 1 or 2. The PM51 derives the
port in `0x69B3`: the first port (0, 1, …) of its own id table (XDATA
`0x6202+port`) whose front-end id matches a bit set in the front-end's message
(byte 0: bit 0 → id 7, bit 1 → 8, bit 2 → 9, bit 3 → `0x0F`, bit 4 → `0x10`;
byte 1: bits 0–4 → ids 1–5; …). `wake-port-first` therefore started the
scan on HDMI 1 in that run.
Traced 2026-10-09: the table is a Keil initialised-data record (PM51 image
`0x248F`: `46 62 02 | 07 08 0B 0C 00 00`), so port 0 = id 7 (USB-C), 1 = 8
(DP), 2 = `0x0B` (HDMI 1), 3 = `0x0C` (HDMI 2). `0x69B3` returns the first
port whose id bit is set, so the message carried HDMI 1's bit (byte 1 bit 6)
and neither USB-C's nor DP's. In the front-end's low-power program the
detector event (`0xA32C2`) of kind 2 takes per-port flags from PM status
`0x3C4` bits 7–12 and `0x3C6` bits 3–7 (`0xA1DF7`), checked per port
6–10 (`0xA2458`) with the enabled detector types (`0xB0000608` bits 0–2);
the mask is sent shifted by 8. Port n there is front-end id n + 5
(`0xA1ED4`), so n = 6 is id `0x0B`: the front-end itself reported an HDMI 1
detector event with nothing connected. Which detector type fired (and
whether a flag latched from the scan's HDMI 1 HPD pulses, §49 log 6.97 s,
is the source) is not established. Only one occurrence so far.
Owner (2026-10-09): the monitor has woken from deep standby without a
source change now and then (from memory); to be observed before any change.
PC kernel log (amdgpu, through the dock) at the deep-standby entry: one
`DMUB HPD RX IRQ` (short pulse), no disconnect; KDE kept the output.

**Measurement** (owner, 2026-10-08; nothing charging from the monitor):
- Link-held standby: 12.2 W / 12.7 W (two readings).
- Main supply cut in link-held standby (`tools/glowtest.sh 7`: `0x434` bit 7
  low; the CPU stops, mains cycle afterwards): 4.1 W / 3.7 W. The PC kept
  listing the monitor as connected, with no disconnect message. The ten
  kernel lines `journalctl -kf` showed (00:38:21) are most likely its backlog
  from the earlier toggle (00:38:11), not from this test (to be confirmed).
  So HPD stayed asserted: the front-end is not on the switched supply.
- Deep standby (§16): 1.2 W.

So about 8.5 W are in the main domain (scaler chip, memory and what else the
switched supply feeds), and about 2.5–3 W more are saved in deep standby,
most likely by the front-end's own low-power mode. Whether the front-end kept
the DP link trained after the cut (not only HPD) was not observable.

**Vendor hand-off for comparison** (`sub_23D6AA` → `0x20E56B`): no partial
power-down. Receivers to mode 5 (`sub_20ED62` → `sub_20FFB2`), per port
`sub_20EDCC(id, 1)` (`sub_23EF7E`), power pads, clock gates `0x2B08`/
`0x2B18`/`0x2B28` = `0xFFFF`, PM wake block copied to `0x103380`, CPU parked;
the PM51 then switches its own mode (`0x4BE9`: `0x7E4C(1)` with PM registers
`0x391`, `0x372`, `0x3B8`, `0x3BC`, mode routine `0x76CE`; not decoded) and
cuts the main supply (`0x434` bits 6/7).

## 52. Front-end power modes and wake messages (Option A feasibility, 2026-10-08)

Goal (§51): link-held standby with the main supply off (~4 W) while the
front-end keeps the DP link, instead of 12.5 W with the scaler running.

**Front-end power mode command** (PM51 → front-end, front-end command `0x00`
sub 1, data: mode, 32-bit mask), sent by PM51 `0x8A25(mode)` with the mask in
IRAM `0x28..0x2B`, five tries, answer `0x10` = done:
- mode 3, mask from the main firmware's PM block (`0x5E97`, via `0x8337`):
  standby entry `0x4A29` → `0x4B1A` (state 1);
- mode 2, mask 0: power off (state 2), after `0x20` sub 3 (id, 0) (HPD low)
  for ids 7, 8, 9 (`0x4AAB`; only in state 2, so standby keeps HPD);
- mode 0, mask 0: wake (`0x513E`, `0x5253`);
- mode 1 with mask `0xFFFF`/`0xFF00`/`0x00FF`/0, or mode 2: PM51 local
  command `0x61` sub 3 (`0x4990`, by data byte); the main firmware never
  sends command `0x61`.
PM51 mailbox dispatcher `0x47ED`: main-firmware command `0x60` is forwarded
to the front-end as (sub, data0, data1) by `0x4910`; `0x61` is local
(`0x4939`: sub 0 read, 1, 3 power mode, 4).

**Front-end firmware** (`010F` of V108, `v108_010f.bin`; AEON R2 like the
scaler, uncompressed, load address 0, RAM `0xB000xxxx`):
- Command dispatcher `0x88A63` (from the frame parser at `0x88CDA`):
  `0x00` → `0x88989`, `0x10` → `0x8879D`, `0x20` → `0x8808C`, `0x30` →
  `0x87EF0`, `0x40` → `0x87E03`, `0x50` → `0x87C17`, `0x60` → `0x8787F`,
  `0x70` → `0x87836`, `0x80` → `0x87790`, `0xFF` → `0x8765F`; answer `0x10`
  = done, `0x30` = unknown command.
- `0x00` sub 1 stores mode and mask at `0xB001A799` / `0xB001A79C` (copy at
  `0xB001A13C` when `+0x187` is set).
- Messages to the PM51 (`0xF0`, type, 4 payload bytes; repeated until the
  PM51 acknowledges, `0x88473`): the normal program sends them from a
  pending-flag word `0xB0008FD0` (payloads at `0xB0009ECC + 4 × type`,
  `0x85FE4`), but only types 1, 6, 7, 8 and 9 are ever flagged (6: per-port
  item `0x2B`, HDMI only; 9: per-port item `0x11`, for DP a debounced RX
  flag at `+0xE6` of the RX state, `0x3DE14`; 7, 8: not decoded).
- **Type 0 (the PM51's event 9, "source activity" with connector mask) is
  sent only by a separate low-power program** in the image (`0xA0000`
  region, own RAM `0xB0000xxx`, sender `0xA4730`, callers `0xA6E30`ff: types
  0, 5, 2, 3), i.e. in the standby mode.
- PM51 side (`0x5ED5`): every type sets a flag (`0x6332` bits 0–7 = types
  0–7, `0x6331` bits 0–1 = types 8–9) and stores the payload at
  `0x6309 + 4 × type`; only type 0 (event 9) and type 4 (events 5/6/7)
  lead to a wake.

**Consequence for Option A:** skipping mode 3 at standby entry keeps the
front-end's normal program (and most likely the DP link) running, but then
no event 9 arrives at all: neither when the source starts video nor when a
source appears on another connector. Option A therefore also needs a wake
source in that state: one of the normal program's messages (types 7–9,
meanings open) or a front-end query that the PM51 polls. Not identified yet.

## 53. Front-end modes 1–3, queries and a video signal for Option A (2026-10-08)

**Power modes in the front-end** (`0x00` sub 1 → after the answer, the frame
handler `0x88D0E` calls `0x142BD(mode, mask)`):
- Mode 0: nothing happens (normal operation continues).
- Modes 1, 2 and 3 all leave the normal program: mode and mask go to RIU
  `0x102A00`–`0x102A0B` (`0x8D28F`, flag `0x10211E`), the receivers are
  switched off (`0x25375` for 0–2, `0x24E31(mode)`; mode 2 also `0x25135`,
  `0x1425E`, `0x142A1`), the low-power program (file offset `0xA0000`,
  `0x14000` bytes) is copied to address 0 and started.
- Low-power program (main `0xA102C`): reads mode/mask back (`0xA175A` →
  RAM `0xB0000C14`/`0xC18`, `0xA1C07` → `0xB0000C20`), CPU clock 923 kHz in
  mode 2, 12 MHz in modes 1/3 (`0xA1C4B`). Modes 1 and 3 arm the connector
  detectors from the mask (`0xA3C94`: low 3 bits and bits 8–18); mode 2 arms
  nothing. On a detector event (`0xA32C2`, PM status `0x3C4`–`0x3C6`) it
  sends message type 0 with the connector mask (`0xA3DC3`, payload
  `0xB0000BC8`) = PM51 event 9. Afterwards mode 3 stops (state 2) while
  mode 1 re-arms and keeps reporting.
- So mode 1 is not a partial normal mode: it is the same low-power program
  as mode 3, without the main link; it is of no use for Option A or B.

**Message types of the normal program** (§52), decoded further:
- 9: per-connector item `0x11` = the DP receiver's plug/cable detection
  (`0x3DE14`: pins at `0xA00008E9` bits 1/3 and PM `0x475` bits 1/3/5,
  debounced), not video.
- 7: status of the output paths to the scaler (`0x8692D`, transmitter items
  `0x0D`/`0x09` via `0x27DF7`); with the scaler off the transmitter has no
  sink, so it is unlikely to report anything useful.
- 6: HDMI only; 8: not decoded.

**Front-end commands usable from outside** (main firmware → mailbox → PM51
→ front-end; command, sub, x and data reach the front-end unchanged):
- `0x60`/`0xFF`/x with data [id] (`0x87B00`, jump table at
  `0xA354`): x `0x0B` link status (the standby gate's query,
  `0x24E79` → `0x3D536`), x `0x0A` DPCD `0x202`/`0x203` lane status, x `0x09`
  DPCD read for a few addresses only (`0x50471`: `0x000`–`0x002`, `0x00E`,
  `0x111`, `0x160`, `0x202`, `0x203`, `0x270`, `0x300`–`0x30B`,
  `0x2200`–`0x2211`; not `0x600`, not `0x205`).
- `0xFF`/`0xFF`/x 2 with data [address, 4 bytes big-endian] (`0x87759`):
  reads one byte of the front-end's register space (`0x13EFC` → RIU read
  `0x8D6C5`). Sub 3 of the same command writes (`0x13F0C`); never used.
- Front-end ids → DP receivers (`0x12C7F`, `0x36360`): id 7 (USB-C) =
  receiver 0, id 8 (DP) = receiver 1.

**Receiver registers** (front-end RIU):
- DPCD banks per receiver: `(rx << 8) + 0x1100` and `+ 0x1400` (DP:
  `0x1200`, `0x1500`).
- Link block `0x110000 + 0xA00 × rx`: lane status `+0x32E`/`+0x32F`
  (DPCD `0x202`/`0x203`), training state `+0x541` (low bits).
- Stream timing (MSA) of DP decoder d: 16-bit at `0x113068 + 0x100 × d`:
  `+0` htotal, `+2` vtotal, `+4` width, `+6` height, `+8` hstart, `+0xA`
  vstart, `+0xC` hsync, `+0xE` vsync (15 bits; `0x39CD1`; order measured,
  §54). The decoder of a
  receiver comes from RAM (`0x4DEE1`), so all four blocks are read.
- Where the source's DPCD `0x600` (D0/D3) lands is not identified (the
  `0x600` constants in the code belong to the transmitter side, `0x42D1C`ff).

**`diag-fe` v3** (register mode): VCP `0xED` = `0x300 | n` reads n (≤ 32)
bytes from the diag-poke address (VCP `0xEA`/`0xEB`) with the debug read,
into RAM `0x202480`; only `0x001100`–`0x0016FF` and `0x110000`–`0x113FFF`
are sent (others read 0). `tools/fereg.sh preset dp` reads the DP receiver's
DPCD banks, link block and the four MSA blocks.

**Plan:** read them with a picture and in link-held standby (link held, no
video) and compare. If the MSA timing (or another register) separates the
two, the PM51 can poll it in Option A's state (front-end in mode 0, main
supply off) with the same command, together with the link query `0x0B` to
notice the link being released (then mode 3, real deep standby).

## 54. Video signal for Option A found: the receiver's MSA registers (2026-10-09)

**Measurement** (`diag-fe` v3, `tools/fereg.sh`; DP from the dock, 4K 144 Hz
with DSC; then the PC's DP output disabled → deep standby (the dock had
released the link), key wake → link-held standby, `fequery r8` = source
active). Files of the owner, 2026-10-09 01:42–01:58.
- MSA block of decoder 1 (`0x113168`), with picture: htotal `0x0FA0` (4000),
  vtotal `0x08AE` (2222), width `0x0F00` (3840), height `0x0870` (2160),
  hstart `0x70`, vstart `0x3B`, hsync `0x40`, vsync `0x8005` (bit 15 =
  polarity). Field order is therefore htotal, vtotal, width, height, hstart,
  vstart, hsync, vsync (the §53 names for +4…+0xE were wrong).
  4000 × 2222 × 144 Hz = 1.28 GHz pixel clock (CVT-RB2 4K 144 Hz).
- Link held without video: decoder 1 reads `78 00 4B 00 50 00 3C 00 12 00
  05 00 0C 00 02 00` (120, 75, 80, 60, 18, 5, 12, 2), identical to the
  unused decoders 0 and 2 in both states, i.e. the register defaults.
  Decoder 3 reads 0.
- Link block: lane status `0x110D2E`/`0x110D2F` = `0x77` in both states
  (link trained also without video). `0x110D32` and `0x110F40` = `0x14`
  with picture, `0x1E` without: the dock trained HBR2 for the stream and
  HBR3 for the empty link.
- DPCD banks: differences at `0x121C`, `0x1226` (3 → 5), `0x1234`/`0x1235`,
  `0x1238`, `0x123A` (`0x0D` → 1), `0x1278`, `0x151B`/`0x151D`, `0x15A9`,
  `0x15E0` (5 → 8). Which of them is DPCD `0x600` is not established.

**Signal:** "video on a DP receiver" = an MSA block with a width above the
default (e.g. > 256): readable with the front-end's debug read
(`0xFF`/`0xFF`/2) from the main firmware and, in principle, the PM51. Not yet
verified: that the front-end keeps decoding MSA while the scaler (the
transmitter's sink) is off, and which decoder USB-C uses (all blocks can be
checked).

**Message type 8** (§52/§53), decoded: routing report. `0x8631D` (on a
change of the front-end's active receiver, `0x25AC1`) and `0x862A4` (on a
change of an output path's input mask, `0xB0008FD4 + 0x1C × path`) send the
packed indices of the routed inputs (`0x12FDB`: one nibble per set bit) at
payload `+0x21`/`+0x22`; `+0x20` = 1 when more than one input or when query
`0x0C` reports 7. It follows the main firmware's input selection, not video.

## 55. Option A implemented: `gate-all-dp` v5 + `pm51-hold-link` (2026-10-09, hardware-tested)

**Checked before building:**
- The main firmware's hand-off (`sub_26136B` allowed path, `sub_245787`,
  `sub_261910`, `sub_245860`, `sub_23D512`, `sub_23D6AA`) sends no
  front-end command (no path to `mailbox_query`).
- The PM51's standby entry (`0x3ED9` → `0x4A29`, state 1) talks to the
  front-end only in `0x78FF` (check: `0x20` sub `0x14` = `0xFFFFFFFF`
  (`0x13107`), `0x20` sub `0x0B` index 2 (`0x13E4D`), echo `0xFF`/`0xFF`/0)
  and in `0x8A25(3)` (mode 3). HPD low (`0x20` sub 3, level 0, ids 7–9) is
  sent only for power-off (state 2). So skipping mode 3 is enough to keep
  the front-end's normal program and the link.
- Standby block (`0x48A740`, copied to RIU `0x103380`, PM51 copy `0x8958`:
  byte-swapped words into XDATA `0x5E93`ff): +0/+1 → `0x5E94`/`0x5E93`
  (request), +2/+3 → `0x5E96`/`0x5E95` (port; the PM51 never reads
  `0x5E95`), +4/+5 → `0x5E98`/`0x5E97` (suppress mask, fixed input only).
- PM51 sleep loop `0x9BA5`: `0x880F` (1-second task; bit `0x21.0` is the
  timer ISR's per-second flag, `0x25E5`/`0x887B`), `0x9665`, `0x952C`,
  classifier `0x5BAA` until it reports an event; it never halts. XDATA RAM
  is `0x5000`–`0x7FFF` (startup `0x2AD5`); the firmware uses up to `0x634A`
  and `0x7337`.
- PM51 → front-end transfers: `0x64A4` (r7 command, r5 sub, r3 x; IRAM
  `0x36/0x37` tx length, `0x38–0x3A` tx generic pointer, `0x3C/0x3D` rx
  length, `0x3E–0x40` rx pointer; r7 = `0x10` when answered).

**`gate-all-dp` v5 (main firmware):** at the end of every gate call
(`g_hold`, `0x202520`): refused only because of active links (no failed
query in this call, not the routing tick) → allowed, RAM `0x2024C6` =
`0x80 | connectors` (bit 0 USB-C, bit 1 DP). The power-save entry writes it
to block +3 (`g_blk` `0x202500`, hook `0x261425`). A failed query still
refuses (`0x2024C5` = 1; link-held standby with the CPU running).

**`pm51-hold-link` (PM51 bank 0 `0xA200`–`0xA3C3`, XDATA `0x7F00`ff):**
- `0x4AF1` → `pre`: hold off at every standby entry.
- `0x4B1A` → `mode`: hold byte set → no mode 3, save the wake mask, hold on.
- `0x9BB0` → `sec`: counts seconds.
- `0x9BB9` → `poll`: after the stock classifier, once per second in hold:
  link query ids 7 and 8 (`0x60`/`0xFF`/`0x0B`); a new active connector
  (not suppressed) → wake; MSA width high byte of decoders 0–2
  (`0x11306D`/`0x11316D`/`0x11326D` via `0xFF`/`0xFF`/2) ≠ 0 → wake (port
  of the held connector, 5 if both); no link left → `release` (mode 3 with
  the saved mask = stock deep standby); 3 rounds with a query unanswered →
  `release`. Wake = event 9 with the port (`0x5E89`/`0x5E8A`, `0x23` = 1).

**Expected:** link-held standby at ~4 W instead of 12.5 W, no wake loop;
picture ~1 s + start-up after the source starts video; key wake as before.

**Known limits / risks:**
- Not verified that the PM51's frames work in its standby clock mode
  (failure → release to the stock deep standby after ~3 s, i.e. as before)
  and that the front-end decodes MSA with the scaler unpowered (failure →
  no wake on video; a key wakes).
- If the release's mode 3 itself fails, only keys wake the monitor.
- With both DP and USB-C held, only the routed input's decoder may carry
  MSA; video on the other one is then not seen (a key wakes).
- If a stream is present at standby entry (e.g. the black-screen cases of
  §40), the PM51 wakes at once: a ~30 s standby/wake cycle instead of a
  monitor stuck on.
- Readable for tests: `0x2024C6` (hold byte of the last gate call; written
  only at the standby decision at the end of the countdown, so 0 while "No
  signal" is shown), `0x2024C5` (failed query), after a wake
  `0x453C74`/`0x453C78` (event 9, port).

**Hardware test** (owner, 2026-10-09, build `diag_v17` = full list +
`pm51-hold-link`; automatic input; PC → USB4 dock → DP):
- PC output disabled, dock holds the link → after the countdown ~4 W
  (instead of 12.2–12.7 W); no hot-plug at the PC, no wake for 3+ minutes.
  DDC/CI no longer answers (scaler off), as in deep standby.
- PC output enabled → picture; `0x453C74` = `0x09`, `0x453C78` = `0x01`
  (event 9, port DP): the PM51's frames work in its standby clock mode and
  the front-end decodes MSA with the scaler unpowered.
- Output disabled again → this time deep standby (power reading unstable:
  0.00 W with spikes to 2.6 W on the owner's plug; earlier 1.2 W steady).
  Whether the hold was entered and released at once (dock released the
  link, as seen in §54) or not entered is not established. Wake by enabling
  the output worked.
  The unstable reading is the plug: the same with no cable connected
  (stock deep standby).
- Menu key wake: `0x453C74` = `0x11`, port 1; quick.
- DP cable pulled during the hold → deep standby at once (release path).
- USB-C video (laptop, DP output of the PC disabled): MSA of **decoder 1**
  (`0x113168`): htotal 4400, vtotal 2250, 3840 × 2160, hstart 384, vstart
  82, hsync 88, vsync 10 (CTA 4K 60 Hz). Decoder 1 serves the routed
  receiver for both DP and USB-C; decoders 0 and 2 stay at the defaults.
  Hence the limit above holds: with both connectors held, video on the
  non-routed one is not seen by the MSA check (a new link is still seen).

## 56. OSD font: format and options for a replacement (2026-10-09)

**Text glyphs** (proportional text, rendered into font RAM by `0x27C046`):
- Font table in RAM `0x3BB068` (pointer `0x453DE8`, set at `0x25980B` and
  others), 40 bytes per glyph, index `(set << 8) + code`. Byte 0: high
  nibble 1–3 (0xF = special), low nibble = blank columns to the right of
  the glyph (advance); byte 1: unknown (0 for Latin, small values for CJK);
  then 19 rows of 16 bits, little-endian, MSB = leftmost pixel. 1 bit per
  pixel, strokes 1 px wide.
- Set 0: digits, punctuation, A–Z (`0x20`–`0x39`), a–z (`0x3A`–`0x53`),
  accented Latin (`0x64`–`0x7D`), CJK from `0x60`; set 1: further CJK and
  kana up to `0xDE`; data after that is not glyphs.
- Latin metrics: cap height 10 px (rows 4–13), x-height 7, descenders to
  row 16; widths 5–10 px.

**Icon glyphs** (`0x27BA9E`): the font RAM also takes 2-bit (4-colour)
glyphs: two 12-bit planes per row are interleaved into 24 bits (3 bytes)
per row, written with access mode 3 (`0x101C68`). Used for 8 glyphs from
`0x325CA6` and `0x2C` from `0x3251C2` (`sub_253991`). How the four colours
of such a glyph map to the palette is not traced.

**Font RAM and colour-depth ranges** (`sub_2592D6`, `sub_253991`,
loaders `0x27BC9C`/`0x27BA9E`):
- `0x101C08` = `0x220` (also RAM `0x45788A`): font RAM base, in units of 4
  address steps. `0x101C0B` bits 4–5 = 2: a 1-bit glyph takes 3 units
  (18 rows × 12 bits). Address of code c: `(0x220 + 3 × c) × 4` at
  `0x101C66`/`0x101C67`, then mode 3 at `0x101C68` and the data bytes to
  `0x101C66`.
- Code ranges: `0x101C0A` = `0x300`, `0x101C0C` = `0x101C0E` = `0x3FF`
  (`0x23C24F`). Read as: codes below `0x300` 1 bit per pixel, `0x300`–`0x3FE`
  2 bits (4 colours), none with more. The 2-bit icon loads match: 8 glyphs at
  code `0x300`, `0x2C` glyphs at `0x339` (6 units each, address
  `0x220 + 3 × 0x300 + 6 × (c − 0x300)`; inferred from the two load
  addresses, not verified). During the boot logo the 2-bit range starts at
  `0x100` (`0x2538EE`).
- Tile writes (`0x23C635`): tile address to `0x101C66`/`0x67` (mode 0),
  attribute bytes with mode 2, code bytes with mode 1; the code's high bits
  (above 8) come from `0x101C67` bits 0–3 (RAM `0x457889`).
- Open for anti-aliased text: how a 4-colour tile's pixel values 1–3 map to
  the palette (attribute nibbles or fixed entries), the font RAM size (how
  many 2-bit codes fit), and which code slots the text renderer allocates
  per screen.

**Options:**
1. Replace the 1-bit Latin glyphs (about 100) with a better-drawn bitmap
   font in the same box (16 × 19, same codes and advance nibble): heavier,
   even strokes; no code change, data only. CJK glyphs unchanged.
2. Anti-aliased text: the renderer would have to write 2-bit tiles (mode 3)
   and the palette would need intermediate shades per text colour; larger
   change to `0x27C046` and the tile set-up, font RAM use doubles. Not
   assessed in detail.

**Test build** (`diag-osd` + `tools/osdtest.py`, 2026-10-09, untested):
VCP 0xEE writes/reads one OSD register (`0x101C00`–`0x101DFF` only) at the
diag-poke address. `osdtest.py glyphs` loads 2-bit glyphs (band test
`0x3F0`: pixel values 0–3 in 3-px bands; an anti-aliased "Abg" sample
`0x3F1`–`0x3F3`; the band glyph again at `0x3FE`) with the firmware's
loader sequence (`0x101C6D` bits 6–7 cleared, mode 0, address, mode 3, 54
data bytes); `osdtest.py row R` places them in window 1 (the OSD's window,
RAM `0x3C538A` = 1 at init) with the attributes 21 12 2F F2 40 04 84 C8 for
the band glyph. Tile address = `0x101D10`+`0x20`w (16 bit) + row ×
`0x101D12`+`0x20`w + column. Questions: which colours pixel values 1–3 take
per attribute; whether `0x3FE` displays (font RAM size); whether the sample
reads as smooth text.
v1 on hardware: the menu closed at once and could not be reopened while
the tool ran. Cause: the vendor SET path closes an open menu on every VCP
SET (`0x26B211`: OSD state `0x457854` > `0x0D` → `0x4551A4` = 0,
`0x453C70` bit 0 set, bit 15 cleared); the tool's address writes are SETs.
v2 skips that for the diagnostic codes 0xEA–0xEE only (`osd_keep`).

**v2 result** (owner, 2026-10-09; register dump `osd_info.txt`, photo):
- Registers as expected: `0x101C08` = `0x220`, `0x101C0A`/`0B` = `0x300`
  (10 bits; `0x101C0B` bits 4–5 = 2), `0x101C0C` = `0x101C0E` = `0x3FF`.
  Only window 1 (`0x101D20`) is set up: tile base 1 (`0x101D30`), pitch
  62 (`0x101D32`), pixel box `0x2D6`/`0x2EE`–`0x5BE`/`0x4C2` (744 × 468 =
  62 × 26 tiles of 12 × 18). Windows 2, 3 and 7 have no tile area.
- `glyphs` garbled the menu: about 25 tiles of row 12 from column 23 showed
  coloured noise and "0" shapes. The load address of code `0x3F0`
  (`0x4300`) had wrapped to `0x0300` = tile 768 = 1 + 12 × 62 + 23, i.e.
  the glyph bytes were written into the tile entries. `row` (codes
  `0x3F0`–`0x3FE`) showed nothing recognisable.
- Conclusion: tiles and glyphs share one OSD RAM of `0x4000` words; a word
  holds one tile entry (attribute + code, 18 bits) and the address register
  counts words. Tiles occupy the bottom (`0x000`–`0x87F`, 2176 tiles for
  62 × 26 = 1612 used); glyphs start at `0x101C08` × 4 = `0x880`. A 1-bit
  glyph is 12 words (18 rows × 12 bits = 216 bits), a 2-bit glyph 24. With
  the stock ranges the 1-bit codes `0`–`0x2FF` end at `0x2C80` (= the
  firmware's first 2-bit load address), leaving room for 208 2-bit codes
  (`0x300`–`0x3CF`). Moving `0x101C0A` down trades two 1-bit codes for one
  2-bit code (e.g. 2-bit from `0x40`: 560 codes).
- Tool v2: test codes `0x3B0`–`0x3B3` and `0x3CF` (inside the RAM), solid
  base glyph 6 as a position marker before and after the test tiles.
- Tool v2 on hardware: DDC/CI lost about one write in ten (glyph 0x3B0: 52–56
  of 61 writes arrived in four tries); the marker (glyph 6, white) appeared
  at column 1 of row 11, which is the "Picture" line of the left list, so
  tile addressing (base + row × pitch + column) is right. Tool v3: every
  write is checked against the write counter `0x2024B0` and resent when
  lost (data-port writes only advance the RAM pointer when they arrive);
  tiles are written as one run (attributes, then codes) as `0x23C635` does.
  Checked against a simulated monitor dropping 10 % of writes: glyph and
  tile byte streams arrive exactly.
- Tool v3 on hardware: the glyph upload took over 30 minutes (slow DDC/CI);
  `row` showed the marker at column 1 and attribute colours in columns
  2–9 (F2 white, 40 transparent, 04/84 gray, C8 yellow-green, 2F near-black),
  but no band patterns, and columns 10–16 only the background of attribute
  21. The tool had changed `0x101C67` (code bits 8–11) within one code
  run, which the firmware never does; most likely that moved the RAM
  pointer, so most codes were not written where intended. Three unknown
  blue tiles appeared at the right end of the "Input / Output" selection
  bar. Not interpretable as a colour test.
- `diag-osd` v3: firmware-side commands. SET 0xEE = `0x100` loads built-in
  2-bit test glyphs (bands `0x3B0`, solid values 1/2/3 at `0x3B4`–`0x3B6`,
  "Abg" sample `0x3B1`–`0x3B3`, bands `0x3CF`) with the loaders' register
  sequence (`0x23DC0F` masked writes, `0x23DBE4` address, data bytes via
  `0x23D9E7`); `0x200 | row` places a 28-tile test row with the firmware's
  tile routine `0x25C8F5` (attribute RAM `0x3C5389`, code bits 8–11 RAM
  `0x457889`, both restored afterwards). RAM `0x2024B2` counts completed
  commands. Data tables at `0x202A00`/`0x202C00`.
- v3 on hardware: both commands worked; the markers appeared at columns
  1 and 28. The test tiles (codes `0x3B0`–`0x3B6`) showed recurring UI
  shapes (corner, diagonal, dots, line; white, dark and transparent
  pixels in one tile), not the test patterns, and nothing else in the menu
  changed. So the hardware does show codes ≥ `0x300` as multi-colour
  tiles, but my address formula was wrong. Consistent reading: a 2-bit
  code c starts at the same word as a 1-bit glyph, `0x880 + 12 × c`, and
  occupies two code slots (24 words). Then the firmware's icon loads at
  `0x2C80` and `0x31D8` are codes `0x300`–`0x30F` (8 icons) and
  `0x372`–`0x3C9` (44 icons); `0x3B0` is icon 31 of the second set (what the
  photo showed), and v3's own data went to words `0x3D00`+, beyond the last
  code (`0x3FF` ends at `0x3874`), hence invisible. The 2-bit range
  `0x300`–`0x3FE` therefore holds at most 127 glyphs (less 52 icons) unless
  `0x101C0A` is lowered; RAM is not the limit.
- v4: test glyphs at even codes `0x3D0`–`0x3DE` with that formula.
- **v4 on hardware (2026-10-09): 2-bit tiles work.** The test glyphs appeared
  where placed and the "Abg" sample was rendered in four levels, so the
  address formula (`0x880 + 12 × c`, two code slots) is right.
- **Colour rule for 2-bit tiles** (photo colours measured per tile and band,
  matched against the stock palette): pixel value v of a tile with
  attribute fg/bg nibbles shows **palette entry 16 × fg + v**; the
  background nibble is not used. Matches all five groups: fg 2 → entries
  32–35 (black, white, black, black: white bands, black core of the
  sample), fg 1 → 16–19 (… v3 = `2A2A2A`), fg 4 → 64–67 (v1 = `2A2A2A`), fg
  C → 192–195 (grays), fg F → 240–243 (`2A2A2A`, `205060`, `205060`,
  `203040`: the cyan/slate tiles). Black `000000` shows as transparent
  (wallpaper), as palette entry 0 does for 1-bit tiles.
- **Palette** (256 entries): loader `0x2533CE`(sel, first index, table,
  count): mode `0x0A` + index to `0x101C66`, mode `0x0D` + three colour
  bytes per entry (table bytes +2, +1, +0; table order R, G, B), then mode
  `0x0A`/`0x0C` and one flag bit per entry (table byte +3, all 0 in the
  stock tables); sel ≠ 0 uses modes `0x14`/`0x16` (second palette?). Stock
  table `0x3B74B8` (248 entries, loaded by `0x25354E`): 1-bit colours
  0–15 (0 black/transparent, 1 `3F3F3F`, 2 `F1F0F5` white, 4 `2A2A2A`, 5
  `64F4F3` cyan, 8 `9FFF00`, 12 `5596EF`, 14 `FF4A3B`, 15 `0C0C0C`, …) and
  4-entry groups for the 2-bit icons from 16 on. Further tables `0x3B746C`
  (19 entries) and `0x3B7898` (2 entries at 15).
- Consequence for anti-aliased text: a 2-bit text tile with foreground
  nibble f uses entries 16f…16f+3; loading [background, ⅓, ⅔, text colour]
  there gives smooth edges. The background entry must not be pure black
  (transparent key).

**Requested by the owner** (2026-10-09), after the test: anti-aliased font
(option 2), filled selection bar instead of the white outline, finer
transparency steps between solid and the current level 1 (the menu offers
0 = solid … 5), a multiplication sign in "3840 × 2160", rounded menu
corners.

**Other firmwares** (checked 2026-10-09 for smooth OSD text):
- GP27U, M27T20, M27P20P use the same tile OSD driver (same mode values at
  `0x101C68`, same loaders). Their text is 1-bit as well. They have two more
  font-data writers (GP27U `0x26400D`, `0x268311`) that pack three planes
  into 3 bits per pixel (8-colour glyphs) from a byte stream, apparently for
  pictures/icons, not text.
- The LG 28MQ780 runtime uses the OSD bank very differently (hundreds of
  accesses to `0x101D04`, `0x101C04`, `0x101DF8`…; none of the tile-RAM
  modes above). All four, and ours, contain the SDK's GOP (graphics plane)
  driver strings (`MApi_GOP_*`); whether LG draws its OSD as a bitmap plane
  is not verified. A bitmap OSD would be a rewrite of the whole menu, not a
  font change.
- Nothing to take over for anti-aliased tile text; the 2-bit approach of
  this section stays the plan.

**Owner decisions (2026-10-09):** the stock glyphs may be replaced; Noto Sans;
languages English, French, Spanish, German; Chinese and Japanese may be
dropped in the anti-aliased build (separate patch later if needed).

**Text renderer structure** (step 1 of the anti-aliased font, 2026-10-09):
- `0x27C046`(r3 = first code slot, r4 = string in font codes, r5 = length,
  r6/r7/r8, one stack byte; font table pointer `0x453DE8`, mode bytes
  `0x3D47E4`/`0x3D47E3`) renders a string proportionally into consecutive
  1-bit glyphs starting at code `(0x457888 << 8) + r3` (bank byte
  `0x457888`, e.g. 1 for the resolution line `0x25D6E0`). `0x25D952` sets
  the font RAM address of that code (`(base + 3 × code) × 4`, mode 3);
  `0x27BFCF` writes one 12 × 18 tile from 9 words (two 12-bit rows packed
  into 3 bytes each, 27 bytes per tile); the data port auto-increments, so
  tile i lands in code slot + i.
- Callers: `0x259A0E`/`0x259A8E` (popup messages, slot `0x20`), `0x25CEEC`
  (numbers), `0x25CFF6` (ASCII → font codes, e.g. slot `0xB8`), `0x25D6E0`
  (input/resolution information, bank 1).
- Tiles are placed one by one with `0x23C71C`/`0x23C635` (attribute RAM
  `0x3C5389`, code bits 8–11 from `0x457889`).
- For 2-bit text: `0x27BFCF` would write 54 bytes per tile from two planes,
  tile i would occupy codes slot + 2i (the placement loops must step by 2),
  the slots must lie in the 2-bit code range, and the palette group
  16 × fg … +3 of every text attribute must be loaded with [background,
  ⅓, ⅔, text colour]. Open: the full list of slot ranges per menu page
  (static list incomplete; a logging build of `0x27C046`'s arguments would
  give it exactly).

**Menu text and cell budget** (static, 2026-10-09):
- Item text: text items (12-byte entries: +0 flags, +4 column, +5 row, +8
  text function) are placed by `0x255C98` → `0x25CA96`(column, row,
  descriptor): descriptor byte 0 = first code, byte 1 = tile count; the
  tiles get codes first … first + count − 1 (attribute `0x3C5389`, code
  bits 8–11 `0x457889`; flag bit 1 selects bank 1). For 2-bit text the
  loop at `0x25CB9A` must step by 2.
- Page text: `0x259A0E` renders the whole text block of the current OSD
  state (`0x457854`) into consecutive codes from `0x20`: table `0x326C98`
  (per state a pointer to 6 × {u32 string, u16 length}; language order
  English, Chinese, Spanish, German, French, Japanese), strings separated
  by 0, each starting on a new tile. All option values of a page are in
  the block (e.g. state `0x08`, Input/Output: "Select video input source",
  "Select automatically", "USB Type-C", …).
- Tiles per page block (stock widths from the font bitmaps / Noto Sans
  SemiBold 14 px): Input/Output (`0x08`) EN 216/265, ES 215/270, DE
  223/271, FR 217/260; `0x11` 188–208/236–262; `0x14` 152–183/186–226;
  others smaller. Longest single string 15 tiles stock, 16–18 with Noto
  (label column about 20 tiles).
- Budget: 2-bit tiles take two codes; codes from `0x3FF` are the 8/16-colour
  ranges (`0x101C0C`/`0x101C0E`, 10-bit), so 2-bit text must lie below
  `0x3FF`. With the 2-bit range starting at `0x40` there are 958 codes =
  479 tiles; the largest page needs about 270 plus the left list, header
  and values (rendered separately, bank 1). Fits, but the stock 2-bit
  icons at `0x300`–`0x30F` (selection frame, `0x256144`, code bits 8–11 =
  3) and `0x372`–`0x3C9`, and the 1-bit glyphs at `0xFE`/`0xFF` and the
  overlay sets (`0x2A`–`0x77`) must be relocated or kept outside the text
  slots.
- Boot logo (owner's question): the logo glyphs are 1-bit RLE data at
  `0x324CBC` (100 glyphs) in the image; removing them frees image space,
  not OSD RAM. Image space is not the limit for the new font (dropping the
  CJK glyphs frees about 14 KB of font table: about 360 glyphs × 40 bytes).

**Design constraints found while preparing the prototype** (2026-10-09):
- Page text has a hard limit of 224 tiles: it is rendered into codes
  `0x20`–`0xFF` of bank 0 (descriptor byte 0 is 8-bit). Stock widths need
  up to 223 (German Input/Output page). Largest page with Noto Sans
  (integer advances, each string on a new tile): SemiBold 14 px 272,
  SemiBold 13 px 252, SemiCondensed SemiBold 14 px 245 / 13 px 232,
  Condensed SemiBold 14 px 224 (222 with the space 1 px narrower). Only
  **Condensed SemiBold 14 px** fits without squeezing the letter spacing.
- Bank 1 holds the common block (`0x259ACB`: table `0x3BFF18`, slot `0x20`
  → codes `0x120`–`0x17F`, stock 87–95 tiles, Condensed 90–98) and the
  information lines (`0x25D78C` with slots `0x00` and `0xC0` → `0x100`ff,
  `0x1C0`ff).
- Other code users: the 2-bit icons (`0x300`–`0x30F`, `0x372`–`0x3C9`;
  placed with code bits 8–11 = 3 at `0x2552B1`, `0x255386`, `0x2556DD`,
  `0x255A4E`, `0x2561FB`, `0x2562CA`, `0x2597C2`, e.g. the selection frame
  `0x256144`), code bits 8–11 = 2 and 4 at `0x25C6F9`/`0x25C705`, the
  1-bit base glyphs `0`–`0x1F`, and the overlay/logo sets.
- 2-bit text needs two codes per tile; all needs together (page 448 +
  common about 200 + information lines about 80 + icons 104 codes) fit
  into `0x40`–`0x3FE` (958 codes), but not with a single linear mapping:
  a logical → physical code map has to be applied wherever tile codes are
  written (`0x25CA96` loop, `0x23C635`, `0x23C71C`) and wherever glyphs are
  loaded (renderer `0x25D952`, icon loads in `0x253991`).


**Prototype v1: `osd-aa-font`** (2026-10-09, emulator-checked, hardware test
pending; source `tools/patches_src_osd_aa.py`):
- Findings while building it (they correct the plan above):
  - The vendor 1-bit sets reach up to code `0x77`: the overlay loader
    `0x2537EB` loads 96 glyphs from code 0 (tables `0x3B78A0`/`0x3B7BB4`/
    `0x3B7A2A`), `0x2535CB` 85 glyphs from 0, the crosshair image set
    (`0x32644A`) 78 glyphs from `0x2A`; the crosshair is a 12 × 7 tile image
    placed by `0x2595E5` (descriptors `0x3BAFB5`/`0x3BB00E`). The 2-bit range
    can therefore start at `0x78` at the lowest, not `0x40`; with `0x78` all
    vendor 1-bit sets keep working and no range switching is needed.
  - All string placements go through `0x25CA96` (the neighbours `0x25CBBE`,
    `0x25CBE8`, `0x25CCBA` end in a jump to it). With bit 7 of the row
    argument it rewrites only the attributes (selection changes).
  - 1-bit tiles: set pixels take the attribute's high nibble, clear pixels
    the low nibble (palette entries 0–15). 2-bit tiles use only the high
    nibble (entries 16 × f + v), so a text tile needs a palette group that
    holds its background colour as value 0.
  - Letter spacing: the renderer adds `mode & 3` blank columns after each
    glyph (mode byte `0x3CB81C`, written as `movhi 0x3D` / offset `-0x47E4`;
    earlier notes called it `0x3D47E4`): 1 for text, 2 for numbers (mode 2)
    and values (mode 6). Bits 2–3 select left / right (4) / centred (8)
    alignment via the width function `0x27BF37`.
  - Font set 0 codes `0x80`–`0xFE` hold CJK glyphs as well (set 0 has nine
    more at `0x60`–`0x68`, five of them used by the language names).
- Design: font set 0 keeps the vendor record format and holds bit 0 of
  each pixel; the records of set 1 (vendor CJK) hold bit 1 for codes
  `0x00`–`0x7D`. Latin codes get Noto Sans Condensed SemiBold 14 px glyphs
  (width = rounded advance, left blank 0, baseline row 14, coverage → level
  `round(3 × a^0.75)`, faint overhang columns below 0.6 px of ink dropped);
  other codes below `0x7E` keep the vendor bitmap in both planes. The
  renderer's tile helpers (blit, clear, vertical shift, merge, flush) keep a
  shadow buffer for bit 1; the flush writes one 54-byte 2-bit glyph per tile
  at its own address. Logical code L = (bank `0x457888` << 8) + slot maps to
  `2L + 0x38` (L `0x020`–`0x163`), `2L + 0x48` (`0x164`–`0x194`) or
  `2L + 0x4A` (`0x1C0`–`0x1D9`); the icons stay at `0x300`–`0x30F` and
  `0x372`–`0x3C9`. Range start `0x101C0A` = `0x78`; half circles at
  `0x20`/`0x21`. The placement loop writes the mapped codes (a new
  address/mode/code-high run whenever bits 8–11 change) and replaces a text
  tile's attribute fg nibble by a palette group assigned on first use
  (pool 6, 7, 8, 9, B–F, 3–5; not 0, 1, 2, A, which the icons use), loaded
  with [bg, (2bg + fg)/3, (bg + 2fg)/3, fg] of the attribute's 1-bit
  colours. The palette loader `0x2533CE` (sel 0) is hooked: it records
  entries 0–15 and reloads all text groups after each load. The seven
  spacing reads in the renderer are set to `& 0` (Noto advances include the
  side bearings). Code `0x203000`–`0x20371D`, RAM `0x202D00`–`0x202EAF`.
- Page budget with these widths (strings start on new tiles): largest page
  223 of 224 tiles (German Input/Output), common block 97 tiles.
- **Emulator check** (`tools/aeon/aeonemu.py`, `tools/osd_emu_check.py`):
  the vendor init loader, page text renderer and placement loop of the
  patched image run in a small AEON emulator with an OSD register model
  (font RAM bit stream, tile RAM, palette). Result with `popup-flat` and
  `popup-round`: range `0x78`; all 1-bit glyphs below `0x78` and the 2-bit
  icons identical to the build without the patch (half circles moved);
  eight pages in English, Spanish, German and French rendered with every
  tile equal to the expected glyph layout (German Input/Output uses slots
  `0x20`–`0xFE`); text codes `0x078`, `0x07A`, …; attribute `0x3F` → `0x6F`
  (group 6 = `0C0C0C`, `323232`, `595959`, `7F7F7F`), `0x2F` → `0x7F`;
  attribute-only updates keep the codes; non-text descriptors unchanged;
  groups restored after a vendor palette reload; right-aligned values and
  numbers laid out as intended. The emulator stubs the register accessors
  and models the OSD from the hardware tests above; it does not prove the
  hardware behaviour (e.g. timing, the code-high register).
- Not covered: Chinese and Japanese (set-1 glyphs below `0x7E` are
  overwritten; set-0 CJK codes still show at full intensity); information
  lines longer than 26 tiles at slot `0xC0` (unmapped tiles keep their
  vendor code); text placed by anything other than `0x25CA96` (none found).
