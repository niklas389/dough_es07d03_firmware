# dough_es07d03_firmware

Analysis and repair tooling for the scaler firmware of the Dough / Eve
Spectrum **ES07D03** (MStar MST9U4) monitor. It targets the last vendor release,
`Beta03 (rev1169-E771)`.

The vendor firmware is **not** included. Get
`ES07D03_Beta03_rev1169-E771_USB_update.bin`
(sha256 `d9be1e1c7aad81813faa7490a200fe6cfb83d0f371169f4ff94b829ea64c5ce3`)
from the usual public sources. Flashing is done with `specflash` from
[dough-monitor-tools](https://github.com/niklas389/dough-monitor-tools).

| Path | What |
|---|---|
| `docs/firmware-map.md` | Package layout, boot chain, checksums, memory map, located subsystems |
| `docs/flash-reference.md` | SPI flash map, package/section layout, CRCs, USB/ISP flash access (from the hardware sessions) |
| `tools/es07fw.py` | `info` / `unpack` / `patch` / `diff`: verifies and rebuilds packages (deflate + both CRCs); patches the main image or the PM51 code |
| `patches/*.json` | Byte patches by runtime address, with original bytes checked before applying |
| `tools/aeon/aeondis.py` | AEON R2 disassembler (vendor-table driven) |
| `tools/aeon/funcs.py`, `xrefs.py`, `fdis.py` | Function discovery, xref database, annotated listings |
| `tools/aeon/names.txt` | Identified functions |
| `tools/aeon/aeonasm.py` | Minimal assembler used for code-cave patches |
| `tools/aeon/aeonemu.py`, `tools/osd_emu_check.py` | Small AEON emulator (integer subset, OSD register model) and the emulator checks of `osd-aa-font`: runs the vendor OSD code of a patched image without hardware |
| `tools/patches_src_*.py` | Sources that generate the code-cave patches (`standby-lhs`, `panel-t12`, `panel-prepower`, `audio-off`, `eeprom-fast-read`, `popup-flat`, `popup-round`, `diag-poke`, `bl-supply-off`, `diag-log`, `wake-no-replug`, `standby-timeout`, `port-accept`, `pm51-wake-window`, `port-nosignal`, `pm51-input-filter`, `osd-aa-font` (needs the Noto Sans TTF, see its docstring)) |
| `tools/poke.sh`, `tools/fequery.sh`, `tools/fereg.sh`, `tools/osdtest.py`, `tools/glowtest.sh`, `tools/regdump.sh`, `tools/watch.sh`, `tools/logread.py`, `tools/lhspower.sh` | Live register read/write on a `diag-poke` build; guided backlight-glow test (`0x434` bit 7, then bit 6 driven low and restored, pausing for observation); register range dump for before/after diffs; periodic power-state log; `diag-log` reader; guided link-held standby power test (`0x44A` bits 7/6/2/1 driven low one at a time and restored); front-end register reads (`fereg.sh`, `diag-fe` v3); OSD font/tile experiments (`osdtest.py`, `diag-osd`) |

## Quick start

```bash
python3 tools/es07fw.py info ES07D03_Beta03_rev1169-E771_USB_update.bin
python3 tools/es07fw.py list
python3 tools/es07fw.py patch ES07D03_Beta03_rev1169-E771_USB_update.bin fix.bin \
        d6-standby-lock osd-lock-ignore
python3 tools/es07fw.py diff ES07D03_Beta03_rev1169-E771_USB_update.bin fix.bin
specflash dryrun fix.bin && specflash write fix.bin --yes
```

`patch` refuses to run if the input fails its checksums or if any patch site
does not contain the expected original bytes. It re-parses and re-inflates the
output before writing it.

## Patches

| Name | Status | Fixes |
|---|---|---|
| `d6-standby-lock` | analysis-verified | VCP D6=02..04 permanently disabling the OSD (persisted key-lock bit) |
| `osd-lock-ignore` | analysis-verified | Heals monitors that already carry the lock bit in EEPROM |
| `standby-gate` | **tested, does not work** | Enters power-save but is woken at once and reboots; kept for reference |
| `diag-probes` | diagnostic | VCP E0–E9 GET report power-management state |
| `diag-pins` | diagnostic | Like diag-probes, but E2/E5/E7/E8 read live pin registers (backlight enable, VLCD, standby power) and the PM wake status; use instead of diag-probes |
| `diag-poke` | diagnostic | VCP 0xEA/0xEB/0xEC read/write an **allowlisted** set of volatile pin and scaler registers (`tools/poke.sh`); reads with interrupts masked, three agreeing reads per value, also from the PWM units (`0x05xx`, `0x103Cxx`/`0x103Dxx`), the PM51 wake event/port in RAM (`0x453C74`/`0x453C78`) and the settings mirror (`0x4824D0`). No EEPROM, flash, PM51 or factory-data access; a power cycle undoes every write. Combines with `diag-pins`. Earlier versions kept as `diag-poke-v1`/`-v2`; see `docs/diag-poke.md` |
| `diag-log` | diagnostic | RAM timing log (ms time stamps, first 64 events): start-up milestones (init, init done, front-end set-up done, panel preparation, main loop, backlight on), every mailbox command until the backlight is on, port state changes, watched port status/flags, panel on/off callers, OSD timer end, standby gate; read with `tools/logread.py`. Requires `diag-poke`. Code and data in the image head zero area, so it combines with all regular patches. Earlier version kept as `diag-log-v1` |
| `diag-log-mb` | diagnostic | Variant of `diag-log` (same areas: build one of the two): keeps the **last** 64 events and logs every mailbox transaction with its duration for the whole run (no watcher); read with `LOG=diag-log-mb tools/logread.py`. For checking whether the slow mailbox (~66 ms per transaction after a wake) persists (2026-10-07: the link queries take 2–6 ms after a wake too; the slow transactions are specific posted commands, `docs/firmware-map.md` §27) |
| `diag-log-ring` | diagnostic | Variant of `diag-log` (same areas: build only one variant): keeps the **last** 64 events, so loops long after the start stay visible; also watches the current port, the "No signal" restart flags (`0x453C70` bits 15/14) and the states of ports 0 and 1. v2 (2026-10-07): mailbox commands for the whole run (without the periodic `0x20` sub 18), with the hot-plug level, so input switches show their HPD commands; v3: every input selection with its caller. Read with `tools/logread.py` (default `LOG=diag-log-ring`; partial reads are decoded, `-n N` for the newest N entries) |
| `select-no-replug` | **superseded, do not use** | Breaks input switching with DisplayPort Mode "1.4 without DSC" / 1.2: the front-end needs the HPD command to switch (§31). Use `switch-no-unplug` |
| `attach-no-replug` | **superseded, do not use** | Replaced by `switch-no-unplug` (§31) |
| `switch-no-unplug` | **hardware-tested** (2026-10-08, manual switches in DisplayPort Mode 1.4 and 1.4 without DSC; automatic input and wake not yet) | Input switches between DP and USB-C send only "HPD high" to the new connector instead of an unplug pulse; in DisplayPort Mode 1.4, DSC stays advertised on both connectors so nothing the PC reads changes (§31) |
| `gate-raw-id` | **superseded** by `gate-all-dp` | Standby gate asks the current DP / USB-C connector by its own id instead of the `0x30`/7 mapping (§32) |
| `gate-all-dp` | v5 **hardware-tested** (2026-10-09, with `pm51-hold-link`; requires it; `HOLD=0` builds v4.1); v2 **hardware-tested** (2026-10-08); v3 did not help; v4.1 **hardware-tested** (2026-10-08: laptop enabled during the countdown → picture; disabled → deep standby) | Standby gate: with automatic input, standby is refused while a source is active on DP **or** USB-C (the PM51 wakes on either); fixed input: the selected one; a front-end that does not answer: refused (stay responsive). Breaks the standby/wake loop when the dock retrains DP after the monitor slept (§36). v4: in link-held standby, and every 5 s of "No signal" before it, with automatic input the input is routed to a connector with an active link (a newly active one first; with both active, the other one every 30 s), so that connector's video is found, e.g. the laptop enabled while the dock holds DP (§43, §44). v5 (Option A, §55): a source that only holds its link no longer keeps the monitor awake at 12.5 W; standby goes ahead with the request marked "hold the link" (RAM `0x2024C6`, standby block +3), and `pm51-hold-link` keeps the front-end and the link running; a query without an answer still refuses |
| `pm51-hold-link` | **hardware-tested** (2026-10-09: ~4 W in hold, wake on video, key wake, cable pulled → deep standby) | PM51: with the hold mark, deep standby without sending the front-end to its standby mode, so the DP link stays up (DP: the sink keeps its link receiver active while the source holds the link); once per second it asks the front-end for the link status of USB-C and DP and the stream width of its DP decoders: video or a new source → wake (event 9, port); link released → the stock deep standby (1.2 W); 3 s without answers → the stock deep standby. ~4 W instead of 12.5 W in link-held standby; wake ~1 s + start-up (§51–§55). Limit: DP and USB-C share one stream decoder, so with both connectors holding a link, video starting on the non-routed one is not seen (a new link is; a key wakes) |
| `pm51-powerup` | **on hold** (left out of builds since 2026-10-08 until the hang of §39 is explained; it was in that build, not in the first one of §30) | Standby controller, deep-standby wake: 50 ms instead of 100 ms settle time after the power-good poll (GP27U / M27P20P value) (§37) |
| `hpd-skip-unused` | untested | No hot-plug level commands for the two port-table entries without a connector (ports 4/5); never selectable by menu, split screen, the automatic scan or DDC/CI; ~0.2 s less main-loop waiting at every start (§37) |
| `wake-port-first` | untested | Automatic input: a deep-standby wake by a source starts on the input that woke the monitor (PM51 wake port, `0x453C78`) instead of the last one used; saved 8 s (now 2.5 s with `port-nosignal` v4) in a DP wake that started on USB-C (§38) |
| `fe-failsafe` | untested | After a front-end mailbox transaction has timed out (10 s per phase, up to 30 s), the next ones wait at most 0.5 s per phase until one completes again, so keys and the OSD keep working while the front-end does not answer (DDC/CI too, unless its own path fails, §30); normal operation unchanged. RAM `0x2024E0` = 1 while active, `0x2024E1` = number of timed-out transactions (`tools/poke.sh read`) (§39) |
| `picture-watchdog` | v2 untested (v1 fired falsely after a normal attach, §42) | Black screen without "No signal": when the selected input restarts its detection 3 times, each after a no-signal decision, without ever accepting a signal, the input selection is repeated (what the vendor does at menu close, which recovered the picture on 2026-10-08); if the restarts continue, one hot-plug pulse (stock wake behaviour, `PULSE=0` to leave out) and the selection again. RAM `0x2024D1` restarts, `0x2024D2` recoveries (§40) |
| `scan-active-first` | untested (requires `fe-failsafe`, `picture-watchdog`) | Automatic input: the scan asks the front-end which DP / USB-C connectors have an active source; once per search it goes straight to one (DP lost → USB-C without visiting both HDMI inputs, ~2 s less), and it skips DP / USB-C inputs that report no source (2.5 s each); HDMI as stock (§39) |
| `dpmode-same` | **hardware-tested** (2026-10-08) | DisplayPort Mode: selecting the mode that is already set does nothing (stock re-applies it with a 650 ms hot-plug pulse on DP and USB-C, which blanks every monitor behind a dock, and leaves the input disabled). A real change is applied as stock and the input is then enabled again: stock left it disabled whenever the DSC setting did not change (e.g. "1.4 without DSC" ↔ 1.2), giving "No signal" until another input selection or a restart (§45) |
| `nosignal-once` | v3 **hardware-tested** (2026-10-08: deep standby, USB-C replugged → "No signal", scan, "No signal" again, pre-standby; v2 could leave the countdown at 0, §49) | While "No signal" is already shown and its standby countdown runs, the input path's ~8 s detection rounds no longer re-enter it (each re-entry restarted the countdown, so the monitor never reached standby, §33/§34). v3: when a detection restart (scan attach, routing) has cleared the countdown, "No signal" is entered again and reloads it; v2 left it at 0 (black screen, panel on, no standby) |
| `diag-fe` | diagnostic | Requires `diag-poke`. VCP 0xED = connector code (USB-C 8, DP 7, HDMI 1 = 1, HDMI 2 = 3) runs the vendor's front-end link query (`0x30`/7, `0x60`/`0xB`, as in the standby gate) and keeps the answers at RAM `0x2024F0`, with the duration of both transactions (needs a diag-log variant); `tools/fequery.sh` runs it for all four inputs. v2: value `0x100 | id` sends `0x60`/`0xB` for front-end id directly (USB-C 7, DP 8), e.g. `tools/fequery.sh r7 r8`. For the automatic input selection by link status and the slow-mailbox test. v3 (untested): value `0x300 | n` reads n front-end register bytes (DP receiver ranges only) through the front-end's debug read command at the diag-poke address into RAM `0x202480`; `tools/fereg.sh` (presets `dp`, `usbc`, `msa`) for the link-held standby work (§53) |
| `diag-osd` | diagnostic; v4 hardware-tested 2026-10-09 (2-bit tiles and colour rule confirmed, §56) | Requires `diag-poke` and `diag-fe`. VCP 0xEE reads/writes one byte of the OSD register bank `0x101C00`–`0x101DFF` at the diag-poke address (plain register access as the firmware's OSD code; the data port `0x101C66` is never read). v3: SET 0xEE = `0x100` makes the firmware load built-in 2-bit (4-colour) test glyphs, `0x200 | row` place a test row in the open menu (`tools/osdtest.py load` / `row R`), to find how 4-colour tiles map to the palette and how far the font RAM reaches (§56). Only OSD display state changes; a menu redraw or power cycle restores it |
| `panel-t12` | analysis-verified | Enforces the panel's ≥1 s VLCD-off time (T12): panel-on waits for the vendor's own 1.2 s off-timer, which nobody checked; no delay when the panel was off long enough |
| `panel-seq` | **experimental** | One-shot proper panel-off in pre-standby; cancelling pre-standby uses the full panel-on with eDP link training (likely wake-flash cause) |
| `standby-lhs` | **hardware-tested** (2026-10-05: no panel flash at the end of the countdown; reaches deep standby, 1.2 W, stays there; wake and power key work; power-key fix 2026-10-04) | Link-held standby: while the source keeps the DP link up without video, stay dark with the standby LED instead of looping through "No signal"; wake on valid video or key; deep standby once the link is released. Includes panel-seq (use one or the other) |
| `no-logo` | **experimental** | Skips the 2–3 s power-on logo and the forced input re-detection plus panel off/on that follow it; power-on then takes the standby-wake path |
| `pm51-wake-recheck` | **superseded** by `pm51-wake-window` (2026-10-07: a USB-C source behind a dock did not wake the monitor; the 200 ms re-read loses one-shot wake events) | PM51 standby controller: port activity wakes the monitor only if it is still present 200 ms later (the vendor check is a stub that always wakes); keys unaffected |
| `pm51-wake-window` | untested | PM51: port activity wakes the monitor as in stock, except during the first 5 s after standby entry (the AUX burst caused by the entry itself); as in stock, any port wakes regardless of the selected input (the stock port mask only changes the reported port; `docs/firmware-map.md` §21). `WAKE_WINDOW=n` in `tools/patches_src_pm51_wake_window.py`. Do not combine with `pm51-wake-recheck` |
| `pm51-input-filter` | untested | PM51: with a fixed input, a source wake reported by the MSB3300 (event 9, connector mask) wakes the monitor only if the selected input is active; with "Select Automatically" nothing changes (LG 28MQ780 behaviour). Uses the stock suppress list the main firmware sends at standby entry. Combines with `pm51-wake-window` |
| `wake-no-replug` | v4 untested (v3 in daily use; v2 **hardware-tested** 2026-10-07: no disconnect, picture after ~9.3 s) | After a deep-standby wake (PM `0x3AA` bits 4:2 = 1), DP and USB-C (front-end ids 8 and 7; v3: DP only) are re-enabled without their HPD-low step `(id, 0, 0)` in the first 5 s, so neither PC sees an unplug or a "new output"; HDMI keeps the vendor pulse (§35) |
| `standby-timeout` | **hardware-tested** (2026-10-07) | "No signal" → power-save after 30 s instead of 255 s (panel and backlight still off after 5 s); other values with `STANDBY_S=n` in `tools/patches_src_standby_timeout.py` |
| `port-accept` | **hardware-tested** (2026-10-07) | Signal on input ports 0 and 1 (type `0x20`; port 1 = DP input) accepted after 30 × 20 ms = 0.6 s instead of 80 × 20 ms = 1.6 s (LG 28MQ780 firmware, same SDK, uses 30); other values with `ACCEPT=n` in `tools/patches_src_port_accept.py`. See `docs/firmware-map.md` §17 |
| `port-nosignal` | v4 **hardware-tested** (2026-10-08, automatic input: DP output off → USB-C picture 6.8 s, USB-C → DP 4.2 s; requires `nosignal-once`) | Declare an input "no signal" after 2.5 s instead of 8 s (DP / USB-C) and 10 s (HDMI): faster automatic switching and a faster way to "No signal" and standby. `NOSIG_DP` / `NOSIG` (passes of 20 ms) set the values (§37) |
| `port-nosignal-v2` | superseded | DP at 4 s, USB-C at 8 s: with the input fixed to DP, "No signal" flickered every 4 s and the monitor never reached standby (2026-10-07; 4 s < the 5 s pre-standby countdown). Source at commit `d3e91e3` |
| `port-nosignal-v1` | superseded | DP and USB-C at 4 s: USB-C wakes through a dock showed "No signal" and returned to standby (2026-10-07) |
| `panel-prepower` | **hardware-tested** (v2, 2026-10-07: deep-standby wake 6.7–6.9 s with `port-accept`, was 9.3 s; power-key start 6.6 s, was 8.4 s) | Powers the panel up (backlight off) during start-up, so only the backlight step is left when the input is ready; requires `standby-lhs`. v2: the 550 ms panel wait runs as a timer in the main loop (as in the LG 28MQ780 firmware) instead of blocking the start; same order of panel steps, training → backlight still ≥ 550 ms. v1 (blocking) kept as `panel-prepower-v1` |
| `audio-off` | **experimental** | Skips the headphone DAC power-up (~350 ms of anti-pop waits at every start and wake); the 3.5 mm output stays silent |
| `popup-flat` | **hardware-tested** | One-line OSD popups (No signal, input name, …) as one see-through gray box with white centred text, without the empty header band; the menu is unchanged |
| `popup-round` | **hardware-tested** | Rounded corners (6 px) for the `popup-flat` popups; requires `popup-flat`. Assumes OSD colour 0 is transparent: if the corners show a colour, leave it out |
| `osd-aa-font` | **experimental**, v2, emulator-checked (`tools/osd_emu_check.py`); v1 on hardware 2026-10-09: wrong string parts and wrong colours (fixed in v2, §56); v2 hardware test pending | Anti-aliased menu text: Noto Sans Condensed SemiBold 14 px drawn as 2-bit (4-level) glyphs with smooth edges in each text colour (own palette group per text colour). Languages English, Spanish, German, French; **Chinese and Japanese are not readable with this patch** (their glyph set holds the second bit plane). Font licence: `docs/licenses/NotoSans-OFL.txt` (§56) |
| `bl-supply-off` | **hardware-tested** (two monitors, 2026-10-05: dark at once in standby, repeated wakes incl. deep standby) | Standby backlight glow: panel-off also switches the LED supply off (`0x44B` bit 3, which the vendor only clears for deep standby); panel-on switches it on before VLCD. Requires `standby-lhs`. **Limitation:** a menu key press in standby wakes the monitor with a dark panel; the OSD appears once the PC sends video |
| `eeprom-fast-read` | **tested, does not work** | Reads the settings EEPROM at ~200 kHz instead of ~100 kHz. On hardware, power-key off → on then shows "No signal" and returns to standby (mains start unaffected); cause not identified. Kept for reference |

**Hardware status (2026-10-03, one monitor):** the build
`d6-standby-lock osd-lock-ignore panel-t12 standby-lhs no-logo panel-prepower
audio-off eeprom-fast-read pm51-wake-recheck diag-pins` boots, keeps its
settings and works in normal use. The specific behaviour of the
standby/wake patches is still being observed.

**2026-10-04:** that build showed "No signal" for about 5 s and then went
to standby after power-key off → power-key on (stock: picture). Bisected
to `eeprom-fast-read` (fails alone with `d6-standby-lock osd-lock-ignore
panel-t12`; the same build without it works). It is excluded from builds.

Recovery from any bad flash: flash the stock package. If FW2 fails its CRC,
the bootloader falls back to the factory image at SPI `0x0`.

`es07fw.py patch` refuses patches that list each other under `conflicts`.

**Open items:**
- Front-end failsafe (planned, not built): after a timed-out front-end
  command, shorten the mailbox wait (10 s per phase) until a command succeeds
  again, so a monitor with a dead MSB3300 starts in seconds and stays
  reachable for reflashing (`docs/firmware-map.md` §22).
- `pm51-wake-window` acts only on event 2. The re-wake right after standby
  entry (automatic input, 2026-10-07) was event 9 from DP, so the window does
  not cover it. Extending it to event 9 risks losing a real wake inside the
  window (front-end messages look one-shot).
- Automatic input selection from the front-end's connector activity instead
  of the sequential scan (to be investigated).

## Exploring

```bash
python3 tools/es07fw.py unpack PKG work/
cd work
python3 ../tools/aeon/funcs.py runtime_0x200000.bin 0x200000 0x200000 0x2ae000 funcs.pkl \
        0x2ae000 0x453e78 0x26f528 0x2a7af4
python3 ../tools/aeon/xrefs.py runtime_0x200000.bin 0x200000 funcs.pkl xrefs.pkl
cp ../tools/aeon/names.txt . && python3 ../tools/aeon/fdis.py 26ad19 | less
```

## Credits / licences

The AEON R2 instruction tables in `tools/aeon/isa_r2.json` are derived from
[eb4x/ghidra-plugin-aeon](https://github.com/eb4x/ghidra-plugin-aeon)
(Apache-2.0, see `NOTICE`).
