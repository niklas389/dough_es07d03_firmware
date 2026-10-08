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
| `tools/patches_src_*.py` | Sources that generate the code-cave patches (`standby-lhs`, `panel-t12`, `panel-prepower`, `audio-off`, `eeprom-fast-read`, `popup-flat`, `popup-round`, `diag-poke`, `bl-supply-off`, `diag-log`, `wake-no-replug`, `standby-timeout`, `port-accept`, `pm51-wake-window`, `port-nosignal`, `pm51-input-filter`) |
| `tools/poke.sh`, `tools/fequery.sh`, `tools/glowtest.sh`, `tools/regdump.sh`, `tools/watch.sh`, `tools/logread.py`, `tools/lhspower.sh` | Live register read/write on a `diag-poke` build; guided backlight-glow test (`0x434` bit 7, then bit 6 driven low and restored, pausing for observation); register range dump for before/after diffs; periodic power-state log; `diag-log` reader; guided link-held standby power test (`0x44A` bits 7/6/2/1 driven low one at a time and restored) |

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
| `diag-log-ring` | diagnostic | Variant of `diag-log` (same areas: build only one variant): keeps the **last** 64 events, so loops long after the start stay visible; also watches the current port, the "No signal" restart flags (`0x453C70` bits 15/14) and the states of ports 0 and 1. v2 (2026-10-07): mailbox commands for the whole run (without the periodic `0x20` sub 18), with the hot-plug level, so input switches show their HPD commands; v3: every input selection with its caller. Read with `LOG=diag-log-ring tools/logread.py` |
| `select-no-replug` | **superseded, do not use** | Breaks input switching with DisplayPort Mode "1.4 without DSC" / 1.2: the front-end needs the HPD command to switch (§31). Use `switch-no-unplug` |
| `attach-no-replug` | **superseded, do not use** | Replaced by `switch-no-unplug` (§31) |
| `switch-no-unplug` | **hardware-tested** (2026-10-08, manual switches in DisplayPort Mode 1.4 and 1.4 without DSC; automatic input and wake not yet) | Input switches between DP and USB-C send only "HPD high" to the new connector instead of an unplug pulse; in DisplayPort Mode 1.4, DSC stays advertised on both connectors so nothing the PC reads changes (§31) |
| `gate-raw-id` | untested | Standby gate asks the front-end about the current DP / USB-C connector by its own id instead of the `0x30`/7 mapping, which answered "no index" for an unplugged USB-C and so made the gate refuse standby for good (§32) |
| `nosignal-once` | untested | A port already in "no signal" no longer repeats its no-signal decision every 8 s; each repeat re-entered "No signal" and restarted the standby countdown, so the monitor stayed in pre-standby (red LED) and never reached deep standby (§33) |
| `diag-fe` | diagnostic | Requires `diag-poke`. VCP 0xED = connector code (USB-C 8, DP 7, HDMI 1 = 1, HDMI 2 = 3) runs the vendor's front-end link query (`0x30`/7, `0x60`/`0xB`, as in the standby gate) and keeps the answers at RAM `0x2024F0`, with the duration of both transactions (needs a diag-log variant); `tools/fequery.sh` runs it for all four inputs. v2: value `0x100 | id` sends `0x60`/`0xB` for front-end id directly (USB-C 7, DP 8), e.g. `tools/fequery.sh r7 r8`. For the automatic input selection by link status and the slow-mailbox test |
| `panel-t12` | analysis-verified | Enforces the panel's ≥1 s VLCD-off time (T12): panel-on waits for the vendor's own 1.2 s off-timer, which nobody checked; no delay when the panel was off long enough |
| `panel-seq` | **experimental** | One-shot proper panel-off in pre-standby; cancelling pre-standby uses the full panel-on with eDP link training (likely wake-flash cause) |
| `standby-lhs` | **hardware-tested** (2026-10-05: no panel flash at the end of the countdown; reaches deep standby, 1.2 W, stays there; wake and power key work; power-key fix 2026-10-04) | Link-held standby: while the source keeps the DP link up without video, stay dark with the standby LED instead of looping through "No signal"; wake on valid video or key; deep standby once the link is released. Includes panel-seq (use one or the other) |
| `no-logo` | **experimental** | Skips the 2–3 s power-on logo and the forced input re-detection plus panel off/on that follow it; power-on then takes the standby-wake path |
| `pm51-wake-recheck` | **superseded** by `pm51-wake-window` (2026-10-07: a USB-C source behind a dock did not wake the monitor; the 200 ms re-read loses one-shot wake events) | PM51 standby controller: port activity wakes the monitor only if it is still present 200 ms later (the vendor check is a stub that always wakes); keys unaffected |
| `pm51-wake-window` | untested | PM51: port activity wakes the monitor as in stock, except during the first 5 s after standby entry (the AUX burst caused by the entry itself); as in stock, any port wakes regardless of the selected input (the stock port mask only changes the reported port; `docs/firmware-map.md` §21). `WAKE_WINDOW=n` in `tools/patches_src_pm51_wake_window.py`. Do not combine with `pm51-wake-recheck` |
| `pm51-input-filter` | untested | PM51: with a fixed input, a source wake reported by the MSB3300 (event 9, connector mask) wakes the monitor only if the selected input is active; with "Select Automatically" nothing changes (LG 28MQ780 behaviour). Uses the stock suppress list the main firmware sends at standby entry. Combines with `pm51-wake-window` |
| `wake-no-replug` | v3 untested (v2 **hardware-tested** 2026-10-07: no disconnect, picture after ~9.3 s; one later slow wake of ~20 s, cause unknown) | After a deep-standby wake (PM `0x3AA` bits 4:2 = 1), the DP port (front-end id 8) is re-enabled without its HPD-low step `(8, 0, 0)` in the first 5 s, so the PC does not see an unplug (other monitors do not blank). v3: `(8, 1, 650)` and the other ports' (USB-C, HDMI) stock pulses are sent; v2 suppressed all of them |
| `standby-timeout` | **hardware-tested** (2026-10-07) | "No signal" → power-save after 30 s instead of 255 s (panel and backlight still off after 5 s); other values with `STANDBY_S=n` in `tools/patches_src_standby_timeout.py` |
| `port-accept` | **hardware-tested** (2026-10-07) | Signal on input ports 0 and 1 (type `0x20`; port 1 = DP input) accepted after 30 × 20 ms = 0.6 s instead of 80 × 20 ms = 1.6 s (LG 28MQ780 firmware, same SDK, uses 30); other values with `ACCEPT=n` in `tools/patches_src_port_accept.py`. See `docs/firmware-map.md` §17 |
| `port-nosignal` | v3 untested | HDMI ports (2–5) count as "no signal" after 300 × 20 ms = 6 s instead of 10 s: faster automatic input scan. DP and USB-C keep the vendor 8 s. Must stay above 5 s: a port without signal repeats its no-signal decision every period, each repeat re-enters "No signal" and restarts the 5 s countdown to pre-standby (cause of the v1/v2 loop). `NOSIG=n` (275–500) in `tools/patches_src_port_nosignal.py` |
| `port-nosignal-v2` | superseded | DP at 4 s, USB-C at 8 s: with the input fixed to DP, "No signal" flickered every 4 s and the monitor never reached standby (2026-10-07; 4 s < the 5 s pre-standby countdown). Source at commit `d3e91e3` |
| `port-nosignal-v1` | superseded | DP and USB-C at 4 s: USB-C wakes through a dock showed "No signal" and returned to standby (2026-10-07) |
| `panel-prepower` | **hardware-tested** (v2, 2026-10-07: deep-standby wake 6.7–6.9 s with `port-accept`, was 9.3 s; power-key start 6.6 s, was 8.4 s) | Powers the panel up (backlight off) during start-up, so only the backlight step is left when the input is ready; requires `standby-lhs`. v2: the 550 ms panel wait runs as a timer in the main loop (as in the LG 28MQ780 firmware) instead of blocking the start; same order of panel steps, training → backlight still ≥ 550 ms. v1 (blocking) kept as `panel-prepower-v1` |
| `audio-off` | **experimental** | Skips the headphone DAC power-up (~350 ms of anti-pop waits at every start and wake); the 3.5 mm output stays silent |
| `popup-flat` | **hardware-tested** | One-line OSD popups (No signal, input name, …) as one see-through gray box with white centred text, without the empty header band; the menu is unchanged |
| `popup-round` | **hardware-tested** | Rounded corners (6 px) for the `popup-flat` popups; requires `popup-flat`. Assumes OSD colour 0 is transparent: if the corners show a colour, leave it out |
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
