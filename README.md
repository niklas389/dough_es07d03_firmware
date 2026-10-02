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
| `tools/es07fw.py` | `info` / `unpack` / `patch` / `diff`: verifies and rebuilds packages (deflate + both CRCs) |
| `patches/*.json` | Byte patches by runtime address, with original bytes checked before applying |
| `tools/aeon/aeondis.py` | AEON R2 disassembler (vendor-table driven) |
| `tools/aeon/funcs.py`, `xrefs.py`, `fdis.py` | Function discovery, xref database, annotated listings |
| `tools/aeon/names.txt` | Identified functions |
| `tools/aeon/aeonasm.py` | Minimal assembler used for code-cave patches |
| `tools/patches_src_*.py` | Sources that generate the code-cave patches (`standby-lhs`, `panel-t12`) |

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
| `panel-t12` | analysis-verified | Enforces the panel's ≥1 s VLCD-off time (T12): panel-on waits for the vendor's own 1.2 s off-timer, which nobody checked; no delay when the panel was off long enough |
| `panel-seq` | **experimental** | One-shot proper panel-off in pre-standby; cancelling pre-standby uses the full panel-on with eDP link training (likely wake-flash cause) |
| `standby-lhs` | **experimental** | Link-held standby: while the source keeps the DP link up without video, stay dark with the standby LED instead of looping through "No signal"; wake on valid video or key; deep standby once the link is released. Includes panel-seq (use one or the other) |

Recovery from any bad flash: flash the stock package. If FW2 fails its CRC,
the bootloader falls back to the factory image at SPI `0x0`.

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
