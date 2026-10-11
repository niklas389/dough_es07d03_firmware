# dough_es07d03_firmware

Analysis and repair tooling for the scaler firmware of the Dough / Eve
Spectrum **ES07D03** (MStar MST9U4) monitor. It targets the last vendor release,
`Beta03 (rev1169-E771)`.

The vendor firmware is **not** included. Get
`ES07D03_Beta03_rev1169-E771_USB_update.bin`
(sha256 `d9be1e1c7aad81813faa7490a200fe6cfb83d0f371169f4ff94b829ea64c5ce3`)
from the usual public sources. Flashing is done with `specflash` from
[dough-monitor-tools](https://github.com/niklas389/dough-monitor-tools).

> [!CAUTION]
> **Flashing modified firmware can make your monitor permanently unusable.**
> Read this before you build or flash anything from this repository.
>
> - Everything here is provided **as is, without any warranty**, under the
>   terms of the licences below. You flash at your own risk; the authors and
>   contributors are **not responsible** for any damage, data loss, cost or
>   inconvenience, including a monitor that no longer starts, shows no picture
>   or can no longer be updated over USB.
> - A flash can fail through an interrupted or wrong file, a power loss, a bug
>   in a patch or in the tools, or a hardware difference between units. Most
>   patches are **experimental or untested** (see the status column below).
>   Some change the power sequencing of the panel and backlight; a mistake
>   there could in principle stress or damage the panel or its power supply.
> - If the monitor no longer accepts a USB update, recovery can require
>   opening the case and an SPI flash programmer (`docs/flash-reference.md`),
>   which carries its own risk of damage and voids any remaining warranty.
> - There is no manufacturer support and no support obligation from this
>   project. Help in issues is voluntary and may not come.
> - Only flash if you understand these risks and accept losing the monitor.
>   Keep the unmodified vendor package and know the recovery path **before**
>   you flash.

> [!NOTE]
> This is an independent community project. It is **not affiliated with,
> endorsed by, sponsored by or connected to** Eve Devices, Dough, or any
> company that has acquired, succeeded or licensed their products, firmware or
> brands. "Eve", "Dough", "Spectrum" and other names are trademarks of their
> respective owners and are used here only to identify the hardware. MStar,
> MediaTek and other product names likewise belong to their owners.

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
| `tools/patches_src_*.py` | Sources that generate the code-cave patches (`standby-lhs`, `panel-t12`, `panel-prepower`, `audio-off`, `eeprom-fast-read`, `popup-flat`, `popup-round`, `diag-poke`, `bl-supply-off`, `diag-log`, `wake-no-replug`, `standby-timeout`, `port-accept`, `pm51-wake-window`, `port-nosignal`, `pm51-input-filter`, `osd-aa-font` (needs the Noto Sans TTF, see its docstring), `menu-flag-clear`, `pair-replay`, `menu-round`, `osd-transparency`, `lang-latin`, `scan-one-round`) |
| `tools/poke.sh`, `tools/fequery.sh`, `tools/fereg.sh`, `tools/osdtest.py`, `tools/glowtest.sh`, `tools/regdump.sh`, `tools/widthdump.sh`, `tools/cabledump.sh`, `tools/watch.sh`, `tools/logread.py`, `tools/lhspower.sh` | Live register read/write on a `diag-poke` build; guided backlight-glow test (`0x434` bit 7, then bit 6 driven low and restored, pausing for observation); register range dump for before/after diffs; decoded dump of the values that decide the DP input width (half-width picture, `widthdump.sh`); periodic power-state log; `diag-log` reader; guided link-held standby power test (`0x44A` bits 7/6/2/1 driven low one at a time and restored); front-end register reads (`fereg.sh`, `diag-fe` v3); OSD font/tile experiments (`osdtest.py`, `diag-osd`) |

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
| `diag-poke` | diagnostic | VCP 0xEA/0xEB/0xEC read/write an **allowlisted** set of volatile pin and scaler registers (`tools/poke.sh`); reads with interrupts masked, three agreeing reads per value, also from the PWM units (`0x05xx`, `0x103Cxx`/`0x103Dxx`), the PM51 wake event/port in RAM (`0x453C74`/`0x453C78`) and the settings mirror (`0x4824D0`). No EEPROM, flash, PM51 or factory-data access; a power cycle undoes every write. Combines with `diag-pins`. Earlier versions kept as `diag-poke-v1`/`-v2`; see `docs/diag-poke.md` Also reads the PM SAR ADC page `0x3Axx` (cable detect, `tools/cabledump.sh`). |
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
| `scan-active-first` | v2 untested (emulator-checked; requires `fe-failsafe`) | Automatic input: each input that can have a source is visited once per search, then "No signal" at once. DP / USB-C by the front-end's link status (an active source is taken first, "no source" is skipped); HDMI only when its cable is detected (vendor cable detect, check with `tools/cabledump.sh`). With nothing else connected, "No signal" comes at the lost input's own decision (2.5 s) instead of after two rounds over all four inputs (~11 s); laptop active on USB-C after DP is lost → USB-C directly. RAM `0x2024EA` = inputs visited in this search (§39, §59) |
| `scan-one-round` | untested (emulator-checked) | Automatic input: "No signal" after one scan round over the inputs instead of two (the stock limit of 8 no-signal decisions becomes 4, the vendor's factory-mode value); the upper bound when `scan-active-first` finds candidates (§59) |
| `dpmode-same` | **hardware-tested** (2026-10-08) | DisplayPort Mode: selecting the mode that is already set does nothing (stock re-applies it with a 650 ms hot-plug pulse on DP and USB-C, which blanks every monitor behind a dock, and leaves the input disabled). A real change is applied as stock and the input is then enabled again: stock left it disabled whenever the DSC setting did not change (e.g. "1.4 without DSC" ↔ 1.2), giving "No signal" until another input selection or a restart (§45) |
| `nosignal-once` | v3 **hardware-tested** (2026-10-08: deep standby, USB-C replugged → "No signal", scan, "No signal" again, pre-standby; v2 could leave the countdown at 0, §49) | While "No signal" is already shown and its standby countdown runs, the input path's ~8 s detection rounds no longer re-enter it (each re-entry restarted the countdown, so the monitor never reached standby, §33/§34). v3: when a detection restart (scan attach, routing) has cleared the countdown, "No signal" is entered again and reloads it; v2 left it at 0 (black screen, panel on, no standby) |
| `menu-flag-clear` | v2 untested (emulator-checked) | Stock bug: opening the quick input menu sets `0x453C70` bit 16, which blocks the automatic scan's "No signal"; leaving the menu by a key does not clear it, so after a later signal loss the monitor stays on a black screen with the backlight on and never reaches standby (2026-10-09). Clears the bit once the OSD is back in state 6 (no menu); menu-timer path unchanged (§47, §50). v2: also ends a stuck link-event pause (`0x453C70` bit 13): after a DP link event during "No signal" the vendor pauses all input detection while OSD state `0x0D` runs; if that state is left early (a key, a standby request) the pause stays and the monitor keeps a black screen without "No signal" or standby (candidate cause of the black screen after repeated DP unplug/replug). The task then runs the vendor's own clear and restarts detection; RAM `0x2024EB` counts these recoveries (§59) |
| `pair-replay` | untested (emulator-checked) | Half-width picture at 3840×2160 144 Hz: the front-end sends that picture as two halves on its two links to the scaler, and only its routing report (sent on a routing change) pairs them in path 0. A report that arrives before the start-up layout reset (stream already present at the start: first start after a flash, wake with the link held) was lost. Keeps the last report and applies it again through the vendor handler when a single-window layout has path 0 unpaired; RAM `0x2024A0`–`A5` (§58) |
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
| `osd-aa-font` | **experimental**, v5, emulator-checked (`tools/osd_emu_check.py`); v3 hardware-tested 2026-10-09 (colours, layout and backgrounds correct, text slightly blurry); v4 on hardware: text sharper, but the selected item's text sat on a transparent box and the first item's bar touched the header band; v5 (fix for both) hardware test pending | Anti-aliased menu text: Noto Sans Condensed SemiBold 14 px drawn as 2-bit (4-level) glyphs with smooth edges in each text colour (own palette group per text colour). v4: sharper glyphs (FreeType vertical hinting, stems placed on pixel edges, linear 4-level quantisation), a filled rounded selection bar instead of the outline frame (6 px above and below the text, a 3 px gap below the header band; value editors keep a thin outline), and a real multiplication sign in the resolution line (3840 × 2160). Languages English, Spanish, German, French; **Chinese and Japanese are not readable with this patch** (their glyph set holds the second bit plane). Generator needs Pillow and freetype-py. Font licence: `docs/licenses/NotoSans-OFL.txt` (§56) |
| `lang-latin` | untested (emulator-checked) | OSD language limited to English, Spanish, German and French; required by `osd-aa-font` (Chinese and Japanese are not readable with it). Choosing Chinese or Japanese in the menu or over DDC/CI does nothing; a stored Chinese/Japanese setting (vendor firmware, profile) becomes English. The language list still shows both entries (§56) |
| `menu-round` | untested (emulator-checked) | Rounded corners (6 px) for the main menu window, with the corner glyphs of `popup-round` (requires it) (§56) |
| `osd-transparency` | untested (emulator-checked) | OSD transparency in 11 levels (0–10, steps of 4 in alpha) instead of 6 (steps of 8), same range; default level 2 = the vendor's default. A level stored by the vendor firmware keeps its number (half the former step) (§56) |
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

## Licence

| Path | Licence |
|---|---|
| `tools/` (scripts, generators `tools/patches_src_*.py`, emulator, disassembler) | [GPL-3.0-only](LICENSE) |
| `patches/*.json` (generated from `tools/patches_src_*.py`) | [GPL-3.0-only](LICENSE), except the parts named below |
| `docs/` | [CC BY-SA 4.0](docs/LICENSE) |
| `tools/aeon/isa_r2.json` | Apache-2.0, derived from [eb4x/ghidra-plugin-aeon](https://github.com/eb4x/ghidra-plugin-aeon); see [`NOTICE`](NOTICE) and [`tools/aeon/LICENSE-Apache-2.0.txt`](tools/aeon/LICENSE-Apache-2.0.txt) |
| Glyph data in `patches/osd-aa-font.json` (rendered from Noto Sans Condensed SemiBold) | SIL Open Font License 1.1, see [`docs/licenses/NotoSans-OFL.txt`](docs/licenses/NotoSans-OFL.txt) |

Not covered by any of these licences:
- The vendor firmware. It is not included. The `old` fields of the patch files
  hold short excerpts of it, only so that `es07fw.py` can check that a patch
  applies to the right image. No rights to the vendor firmware are granted.
- Firmware images you build. They combine the vendor firmware with the patches;
  the vendor's rights to its part are unaffected.
