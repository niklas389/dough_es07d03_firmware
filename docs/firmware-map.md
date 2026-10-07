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
  - a non-zero answer refuses standby ("link held by the source", §11).
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
