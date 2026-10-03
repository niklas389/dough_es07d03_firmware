> **Provenance.** Written in a separate analysis session and kept here unchanged
> (only this note was added). Its main-firmware addresses use a different base:
> code at `0x300000`, data at image offset + `0x203800`. In
> [`firmware-map.md`](firmware-map.md) the runtime image is linked at
> `0x200000` and the inflated body starts at `0x203800`, so an address here is
> that map's runtime address + `0xFC800` (e.g. `0x35DB21` = `0x261321`).
> The two "8051 banks" in §2 are bank 0 and bank 1 of the PM51 (Keil code
> banking, see firmware-map.md §10).

# ES07D03 (Dough/Eve Spectrum One) — SPI flash & firmware package reference

Scaler: MStar/MediaTek **MST9U4** (signature at package `0xFF00`: `MST9U4 BGA D32133e`).
Main CPU: MStar **AEON R2**, big-endian variable-length instructions (2/3/4 bytes, any
alignment), little-endian data. Disassemble with `eb4x/ghidra-plugin-aeon`,
language `AEON:LE:32:R2-harvard` for the main image, `AEON:LE:32:R2` for sBoot.

Status legend: **[V]** verified on hardware or against both Beta03 and V108,
**[D]** from disassembly, **[?]** hypothesis.

---

## 1. Physical flash map (8 MB used window)

| Range | Contents | |
|---|---|---|
| `0x000000`–`0x150000` | **Factory image V107** (built May 25 2022). Bootloader + fallback firmware. **Never written by updates.** | [V] |
| `0x150000`–`0x400000` | erased | [V] |
| `0x400000`–`0x400000+len` | **FW2 = active firmware**, byte-identical copy of the update package | [V] |
| after FW2 | leftovers of a previously flashed *larger* package (updates erase only their own length) | [V] |
| up to `0x800000` | erased | [V] |
| `0x800000`–`0xC00000` | reads all `0xFF` (beyond part or empty) | [V] |

- Boot: sBoot CRC-checks FW2; on failure it boots the factory image. [D]
- **User settings are NOT in this SPI flash** (dumped before/after a setting change plus
  power cycle: no difference). Off-chip EEPROM or internal NVM. [V]
- Reference packages:
  - Beta03 rev1169-E771: 1,344,628 B, sha256 `d9be1e1c7aad81813faa7490a200fe6cfb83d0f371169f4ff94b829ea64c5ce3`
  - V108 rev1148: 2,069,060 B, sha256 `136d982c65f8c7615c6f5dd4adc6f9bfa8226f1f877e6e6dcff3d7bb28591757`

---

## 2. Package layout (offsets relative to package = relative to flash `0x400000`)

| Offset | Contents | |
|---|---|---|
| `0x000000`–`0x00008F` | 8051 stub | [V] |
| `0x000100`–`0x010000` | **sBoot** (AEON, base 0), identical in all versions; DDR/MIU init, CRC check, inflate | [V] |
| `0x00FF00` | chip signature string | [V] |
| `0x010000`–`0x01B000` | 8051 bank A; its first 0x64 bytes hold the **image header** (§3) | [V] |
| `0x020000`–`0x02B000` | 8051 bank B (identical across versions) | [V] |
| `0x030080` | **container start** (loaded to RAM `0x200000`); stage-2 stub runs at `0x200100` | [D] |
| `0x0311C7` | 3-byte marker `BE AD DE` = container is compressed (inflate path). Without it sBoot DMA-copies the container uncompressed (layout for that mode not worked out) | [D] |
| `0x031280` | build timestamp string, e.g. `Jul 29 2024\0` `11:34:08` | [V] |
| `0x032080` | **section table** (§4) | [V] |
| `0x033880` | **main firmware**: raw deflate stream (container + `0x3800`) | [V] |
| stream end | `u32 LE` decompressed length, then a 2-byte field of unknown meaning (left untouched; boot verified fine) | [V] |
| `0x124D18`… | further sections per table (§4) | [V] |
| `len`–8 | trailer record `55 AA AB CD 00 00 BB B7` | [V] |
| `len` | `u32 BE` outer CRC (§5) | [V] |

Main firmware once inflated (Beta03: 2,426,488 B):
- **Code base `0x300000`**; real code `0x300000`–`0x3A0000`, rest is data/tables. [V]
- **Data address = image offset + `0x203800`** (Harvard split; strings etc.). [V]

---

## 3. Image header at package `0x10000` (u32 LE)

| Offset | Beta03 | V108 | Meaning | |
|---|---|---|---|---|
| `0x10000` | `0x030080` | `0x030080` | container start in package | [D] |
| `0x10004` | `0x200000` | `0x200000` | container load address in RAM | [D] |
| `0x10008` | `0x2F4C91` | `0x2F5A5A` | container end, RAM view (= `0x1000C + 0x1CFF80`) | [V] |
| `0x1000C` | `0x124D11` | `0x125ADA` | container end, package view (= deflate stream end + 6) | [V] |
| `0x10014` | `0x94CD4117` | `0xF3613E44` | **inner CRC** over `pkg[0x30080 : stream_end+6]` | [V] |
| `0x10020` | `0x148470` | `0x1F9240` | **N = package length without the final 4-byte CRC** | [V] |

---

## 4. Section table at `0x32080`

Header: `"TEL\t"` + `58 33 69 00` + `00 7B 00 00` + `u16 BE count`, then `count` records of
11 bytes: `u16 BE id | u32 BE offset | u32 BE size | u8 flag` (flag `04` = deflate). [V]

Beta03:

| id | offset | size | flag | notes |
|---|---|---|---|---|
| 0109 | 0x124D18 | 0x020008 | 00 | raw block (uncompressed AEON code + zero fill) |
| 0110 | 0x144D20 | 0x000020 | 04 | |
| 0111 | 0x144D40 | 0x000020 | 04 | |
| 0112 | 0x144D60 | 0x000950 | 04 | |
| 0120 | 0x1456B0 | 0x000020 | 04 | |
| 0121 | 0x1456D0 | 0x000020 | 04 | |
| 0122 | 0x1456F0 | 0x0011D8 | 04 | font data (`FoNt` magic when inflated) |
| 0817 | 0x1468C8 | 0x001530 | 04 | `MST` container (PQ/gamma tables?) |
| 0827 | 0x147DF8 | 0x000670 | 04 | |
| D000 | 0x148468 | 0x000008 | 00 | trailer `55AAABCD 0000BBB7` |

V108 is the same plus **`010F` at `0x149230`, size `0x0B0008`** (uncompressed
HDMI/TMDS/DSC code ending up at flash `0x549230`–`0x5F9238`). Packages that contain
`010F` (V108, 106) trigger the on-screen **"Processing update..."** stage after flashing;
Beta03 does not contain it and never shows it. [V for the observation, ? for causality]

---

## 5. Integrity checks

**CRC algorithm (both checks):** CRC-32, poly `0x04C11DB7`, MSB-first (not reflected),
init `0`, no final XOR. The MStar BDMA engine computes it; CRC over data + stored CRC = 0. [V]

```python
def crc_bdma(data, crc=0):
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc
```

| Check | Covers | Stored | Checked by |
|---|---|---|---|
| outer | `pkg[0 : N]`, N from `0x10020` | `u32 BE` at `pkg[N]` | sBoot `0x2000` (flash `0x400000`, len N+4, expects 0). Fail → factory image |
| inner | `pkg[0x30080 : stream_end + 6]` | `u32 LE` at `0x10014` | sBoot loader (BDMA during container copy) |

---

## 6. Modifying firmware (validated on hardware)

1. Inflate `pkg[0x33880:]` (zlib raw, `wbits=-15`); deflate end + 6 = `u32(0x1000C)`.
2. Patch the inflated image (address − `0x300000` = offset).
3. Recompress: `zlib.compressobj(9, DEFLATED, -15, 8)`. Beta03 gives ~6.5 KB slack versus
   the original stream; zero-pad up to the original stream end so **no offset moves**.
   sBoot uses stock zlib inflate; trailing zero padding is fine. [V]
4. Recompute inner CRC (`0x10014`, LE) then outer CRC (`pkg[N]`, BE).
5. Re-parse and re-inflate to verify before flashing.

`specpatch.py` implements exactly this; the pipeline was verified by flashing an
unmodified repack (booted as `D03.V108T`, i.e. FW2, not the V107 fallback). [V]

---

## 7. Flash access over USB (VL822 hub, `2109:8886`)

Control transfers only. Full encodings in the `dough-monitor-tools` README.

- **Bus enable:** hub regs `0xF6A0` and `0xF6A1`, set bit 2, then wait 200 ms.
  Read `0xC0/0xF6 wValue=reg`; write `0x40/0xF6 wValue=reg wIndex=data len 0`.
  Without this every read returns `0xFF`. [V]
- **ISP slave `0x49` (`0x92`/`0x93`):** enter `92 'MSTAR'`, exit `92 24`. [V]
- **Every SPI sequence ends with `92 12`.** Missing it after WREN/WRSR/erase makes all
  later reads `0xFF`. [V]
- **Read page (256 B):** `92 10 03 a2 a1 a0` → `92 11` → 8× IN `0xA7/0xA8/0xA9`
  (wIndex `0x93`, 32 B each) → `92 12`. About 9 KiB/s. [V]
- **Write prerequisites:** debug slave `0x59` (`0xB2`): EnterSerialDebug `B2 'SERDB'`,
  EnterSingleStep `B2 10 C0 C1 53` + `B2 80`, vendor handshake, then **set bit 7 of the
  register addressed by `B2 10 00 10 0F D7` and confirm by readback** (flash access
  enable). [V]
- **Erase:** WREN `92 10 06`+`92 12`, `92 10 D8 a2 a1 a0`+`92 12`, poll RDSR until
  `status & 3 == 0` (64 KB blocks). [V]
- **Program:** poll, WREN, `0xB7: 92 10 02 a2 a1 a0`, data via `0xB8` (mid) / `0xB9`
  (last) in 32 B chunks, `92 12` (256 B pages). [V]
- The ISP path works while the AEON firmware is wedged (used for recovery). [V]

---

## 8. Rules and gotchas

- **Never write below `0x400000`.** That is the factory fallback and bootloader.
- Writing a smaller package does not erase the leftovers of a larger one; don't mistake
  them for corruption when diffing dumps. [V]
- Reading flash while the scaler runs contends for the SPI bus with the CPU. The data
  comes out correct, but the monitor can misbehave afterwards. **Power-cycle (DC off ≥10 s)
  after every ISP session.** [V]
- Some state persists outside the SPI flash and survives power cycles and same-version
  reflashes (e.g. the OSD-lock bit set by VCP D6). Flashing a **different** version that
  runs "Processing update..." clears it. [V]
- Keep at least two firmware versions on hand for recovery.
- Patches in `specpatch.py` are written for Beta03 rev1169-E771 only; the tool refuses
  other builds.
