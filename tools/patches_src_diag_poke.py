#!/usr/bin/env python3
"""Source of patches/diag-poke.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

DIAGNOSTIC: read and write a small, fixed set of chip registers over DDC/CI
(VCP codes 0xEA-0xEC, unused by the vendor firmware), for live experiments
such as finding what really switches the backlight off.

  specctl set 0xEA <hi16>     register address bits 31..16
  specctl set 0xEB <lo16>     register address bits 15..0
  specctl get 0xEC            read the byte at that address (0xFFFF = blocked)
  specctl set 0xEC <byte>     write the byte (ignored unless allowlisted, value <= 0xFF)
  specctl get 0xEA / 0xEB     read back the address halves

Addresses use the firmware's own register helpers (sub_23D972 read; writes
to PM pin registers through reg_write_mask 0x23DADB, which holds the lock
shared with the PM51, scaler writes through sub_23D9E7): RIU byte address for PM registers (e.g. 0x00000426), or the
scaler sub-bank form (e.g. 0x2E902F4B = sub-bank 0x2E, bank 0x102F, reg 0x4B).

Safety:
- Writes only to an exact allowlist of volatile pin/scaler registers (WRITE_OK),
  plus PM 0x0393 (rewritten by the PM51 at every sleep and wake) for the
  slow-mailbox test.
  No flash/SPI, EEPROM (incl. its write-protect pin 0x42C/0x42E), PM51,
  clock or factory-data access is possible. Every write is lost at power-off.
- Reads only from the pages in READ_PAGES (PM 0x03xx/0x04xx, PM PWM 0x05xx,
  chip-top pad configuration 0x101Exx, scaler bank 0x102Fxx with any sub-bank,
  PWM unit 0x103Cxx/0x103Dxx, RAM 0x2022xx-0x2024xx for the diag-log data,
  RAM 0x2039xx for older diag-log versions, RAM 0x453Cxx for the wake event and
  wake port that the PM51 reports (0x453C74 / 0x453C78), RAM 0x4824xx-0x4825xx
  for the settings mirror at 0x4824D0; for the half-width DP picture: RAM
  0x3B49xx-0x3B4Bxx window records, 0x47F7xx-0x47F9xx scaler DP receiver
  records, 0x4821xx-0x4823xx input path records; PM SAR ADC 0x3Axx for the
  cable detect, section 59, tools/cabledump.sh); no data-port or controller
  registers whose read could have side effects.
- Addresses 0x20xxxx, 0x3Bxxxx, 0x45xxxx, 0x47xxxx and 0x48xxxx are RAM and are
  read with a plain byte load.
- The two allowlist tables are in the zero area of the image head (TABLES,
  0x201F00), so the code cave 0x203DC0 ends before wake-no-replug (0x203FB8).
- A read runs with interrupts masked (SR IEE/TEE, as the firmware's own
  critical sections at 0x2A74EA do) and is done three times; if the three
  values differ, 0xFFFE (unstable) is returned instead of a value. This stops
  scaler sub-bank reads from returning another sub-bank's register when an
  interrupt switches the sub-bank in between.
- No firmware function is called except the two register helpers; nothing is
  stored in the EEPROM. Power-cycle to undo any experiment.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

CAVE = 0x203DC0                         # after popup-round (0x203D00-0x203D99), below the flags at 0x203FF0
RD_CAVE = 0x203C60                      # stable-read routine, after popup-flat (0x203C00-0x203C44)
ADDR_VAR = 0x3FF4                       # u32 at 0x203FF4 (linker padding, reloaded at boot)
GET_HOOK, GET_CONT = 0x26B17C, 0x26B180  # GET chain: unsupported code (b.movhi r23,0x48)
SET_HOOK, SET_CONT = 0x26B331, 0x26B335  # SET chain: unsupported code (b.movhi r7,0x48)
GET_REPLY = 0x26B1A0                     # reply builder: max 0x3C88/0x3C87, cur 0x3C86/0x3C82, r5 = type
SET_DONE = 0x26AFC9                      # r3 = 0, no reply (as the vendor SET handlers)
RIU_RD, RIU_WR = 0x23D972, 0x23D9E7
REG_WRITE_MASK = 0x23DADB                 # (reg, set?, mask) read-modify-write under the PM51 register lock

WRITE_OK = [0x00000422, 0x00000426, 0x00000428, 0x00000434, 0x00000436, 0x0000043A, 0x0000043B,
            0x0000044A, 0x0000044B, 0x0000044C, 0x0000044D,
            0x2E902F4A, 0x2E902F4B,
            0x00000393]                 # PM 0x0393: 00 after a mains start, 01 after a wake (PM51 sub_88EB), 11 at
                                        # standby entry; written by the PM51 at every sleep/wake. Allowed for the
                                        # slow-mailbox test (write the mains value 00 after a wake).
READ_PAGES = [0x000300, 0x000400, 0x000500, 0x003A00, 0x101E00, 0x102F00, 0x103C00, 0x103D00, 0x202200, 0x202300, 0x202400, 0x203900,
              0x453C00,                 # RAM 0x453C74-0x453C7B: wake info from the PM51 (event +0, port +4), copied at start by sub_20E254
              0x482400, 0x482500,       # RAM settings mirror 0x4824D0 (+0x4F input 0x48251F, +0x59 0x482529, +0xA5 0x482575)
              # half-width DP picture (docs/firmware-map.md section 50), read-only RAM:
              0x3B4900, 0x3B4A00, 0x3B4B00,       # window records 0x3B4950 + 0xB0*w (w 0, 1): +0x0C state, +0x1C flags, +0x88 doubling
              0x47F700, 0x47F800, 0x47F900,       # scaler DP receiver records 0x47F7D8 + 0x74*rx (+0x36 colour format, +0x5C/+0x5D MISC0/1),
                                                  # timing records 0x47F934 + 0x30*rx
              0x482100, 0x482200, 0x482300]       # input path records 0x4821AC + 0xA8*p (+0x0C/+0x0E width/height shown in the OSD)
TABLES = 0x201F00                       # allowlist tables in the image head zero area (diag-log code ends ~0x201610)  # (addr & 0x7FFF00); top byte only for 0x102F00

R0, R1, R3, R4, R5, R6, R7, R8, R9, R23 = 0, 1, 3, 4, 5, 6, 7, 8, 9, 23
ori = lambda rd, ra, v: ('bg.ori', {'D': rd, 'A': ra, 't': v})
mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
beq = lambda a, b, l: ('bg.beq', {'A': a, 'B': b, ';': l})
bne = lambda a, b, l: ('bg.bne', {'A': a, 'B': b, ';': l})
beqz = lambda a, l: ('bg.beqi', {'A': a, 'I': 0, ';': l})
j = lambda t: ('bg.j', {'/': t})
jal = lambda t: ('bg.jal', {'/': t})
lwz = lambda rd, off, ra: ('bg.lwz', {'D': rd, 'A': ra, 'W': off})
sw = lambda off, ra, rb: ('bg.sw', {'W': off, 'A': ra, 'B': rb})
lhz = lambda rd, off, ra: ('bg.lhz', {'D': rd, 'A': ra, 'X': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
srli = lambda rd, ra, n: ('bn.srli', {'D': rd, 'A': ra, 'H': n})
slli = lambda rd, ra, n: ('bn.slli', {'D': rd, 'A': ra, 'H': n})
orr = lambda rd, ra, rb: ('bn.or', {'D': rd, 'A': ra, 'B': rb})
andr = lambda rd, ra, rb: ('bn.and', {'D': rd, 'A': ra, 'B': rb})
const32 = lambda rd, v: [mh(rd, v >> 16), ori(rd, rd, v & 0xFFFF)]

prog = [
 # ---------------- GET (r5 = VCP code) ----------------
 'get_hook:',
 ori(R7, R0, 0xEA), beq(R5, R7, 'g_hi'),
 ori(R7, R0, 0xEB), beq(R5, R7, 'g_lo'),
 ori(R7, R0, 0xEC), beq(R5, R7, 'g_rd'),
 mh(R23, 0x48), j(GET_CONT),                       # replaced instruction, vendor "unsupported"
 'g_hi:', mh(R7, 0x20), lwz(R4, ADDR_VAR, R7), srli(R4, R4, 16), j('g_ret'),
 'g_lo:', mh(R7, 0x20), lwz(R4, ADDR_VAR, R7), ori(R7, R0, 0xFFFF), andr(R4, R4, R7), j('g_ret'),
 'g_rd:', mh(R7, 0x20), lwz(R3, ADDR_VAR, R7),
 jal('chk_rd'), beqz(R3, 'g_blk'),
 j(RD_CAVE),                                       # stable read (rd_cave), returns to g_ret with r4
 'g_blk:', ori(R4, R0, 0xFFFF),
 'g_ret:',                                         # r4 = 16-bit value; max = 0xFFFF, type 0
 mh(R7, 0x45), ori(R6, R0, 0xFF), sb(0x3C88, R7, R6), sb(0x3C87, R7, R6),
 srli(R6, R4, 8), sb(0x3C86, R7, R6), sb(0x3C82, R7, R4),
 ('bt.movi', {'D': R5, 'I': 0}), j(GET_REPLY),
 # ---------------- SET (r6 = VCP code, value u16 at 0x453C84) ----------------
 'set_hook:',
 ori(R7, R0, 0xEA), beq(R6, R7, 's_hi'),
 ori(R7, R0, 0xEB), beq(R6, R7, 's_lo'),
 ori(R7, R0, 0xEC), beq(R6, R7, 's_wr'),
 mh(R7, 0x48), j(SET_CONT),                        # replaced instruction
 's_hi:', mh(R7, 0x45), lhz(R4, 0x3C84, R7), slli(R4, R4, 16),
 mh(R7, 0x20), lwz(R5, ADDR_VAR, R7), ori(R6, R0, 0xFFFF), andr(R5, R5, R6), orr(R5, R5, R4),
 sw(ADDR_VAR, R7, R5), j(SET_DONE),
 's_lo:', mh(R7, 0x45), lhz(R4, 0x3C84, R7),
 mh(R7, 0x20), lwz(R5, ADDR_VAR, R7), srli(R5, R5, 16), slli(R5, R5, 16), orr(R5, R5, R4),
 sw(ADDR_VAR, R7, R5), j(SET_DONE),
 's_wr:', mh(R7, 0x45), lhz(R4, 0x3C84, R7), ori(R7, R0, 0xFF), ('bg.bgtu', {'A': R4, 'B': R7, ';': 's_end'}),
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7),
 ('bt.addi', {'D': R1, 'I': -8}), ('bn.sw', {':': 0, 'A': R1, 'B': R4}), ('bn.sw', {':': 4, 'A': R1, 'B': R3}),
 jal('chk_wr'), beqz(R3, 's_pop'),
 ('bn.lwz', {'D': R3, 'A': R1, ':': 4}), ('bn.lwz', {'D': R4, 'A': R1, ':': 0}),
 srli(R6, R3, 24), beqz(R6, 's_pm'),
 jal(RIU_WR), j('s_pop'),                          # scaler sub-bank register: plain byte write
 's_pm:',                                          # PM pin register: masked writes under the PM lock
 ('bn.or', {'D': R5, 'A': R4, 'B': R0}), ('bt.movi', {'D': R4, 'I': 1}), jal(REG_WRITE_MASK),   # set the 1 bits
 ('bn.lwz', {'D': R3, 'A': R1, ':': 4}), ('bn.lwz', {'D': R5, 'A': R1, ':': 0}),
 ('bn.xori', {'D': R5, 'A': R5, 'O': -1}), ('bt.movi', {'D': R4, 'I': 0}), jal(REG_WRITE_MASK),  # clear the 0 bits
 's_pop:', ('bt.addi', {'D': R1, 'I': 8}),
 's_end:', j(SET_DONE),
 # ---------------- checks: r3 = address -> r3 = 1 allowed / 0 blocked (leaf, r9 kept) ----------------
 'chk_wr:', mh(R5, 0x20), ori(R5, R5, 0), 'w_loop:',          # r5 = table pointer (patched below)
 lwz(R6, 0, R5), beqz(R6, 'no'), beq(R3, R6, 'yes'), ('bt.addi', {'D': R5, 'I': 4}), j('w_loop'),
 'chk_rd:',
 *const32(R7, 0x007FFF00), andr(R4, R3, R7),             # r4 = page
 srli(R6, R3, 24), beqz(R6, 'r_any'),                    # top byte set: only the scaler bank
 *const32(R7, 0x00102F00), beq(R4, R7, 'yes'), j('no'),
 'r_any:', mh(R5, 0x20), ori(R5, R5, 0), 'r_loop:',       # r5 = page table pointer (patched below)
 lwz(R6, 0, R5), beqz(R6, 'no'), beq(R4, R6, 'yes'), ('bt.addi', {'D': R5, 'I': 4}), j('r_loop'),
 'yes:', ('bt.movi', {'D': R3, 'I': 1}), ('bt.jr', {'A': R9}),
 'no:', ('bt.movi', {'D': R3, 'I': 0}), ('bt.jr', {'A': R9}),
]

def build(wtab, rtab):
    p = []
    for it in prog:
        p.append(it)
    out = []
    k = 0
    for it in p:                                           # fill the two table pointers
        if isinstance(it, tuple) and it[0] == 'bg.ori' and it[1]['D'] == R5 and it[1]['A'] == R5:
            out.append(ori(R5, R5, (wtab if k == 0 else rtab) & 0xFFFF)); k += 1
        else:
            out.append(it)
    return S.assemble(out, CAVE)

wtab = TABLES
tables = b''.join(a.to_bytes(4, 'little') for a in WRITE_OK + [0])
rtab = wtab + len(tables)
tables += b''.join(a.to_bytes(4, 'little') for a in READ_PAGES + [0])
code, L = build(wtab, rtab)
assert (wtab >> 16) == 0x20 and (rtab >> 16) == 0x20
blob = code
assert TABLES + len(tables) <= 0x202000 and cur(TABLES, len(tables)) == b'\0' * len(tables)
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-10s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
print('tables at %#x / %#x, end %#x' % (wtab, rtab, CAVE + len(blob)))
assert CAVE + len(blob) <= 0x203FB8             # wake-no-replug from 0x203FB8; panel-prepower flags at 0x203FF0/1, address variable at 0x203FF4
assert cur(CAVE, len(blob)) == b'\0' * len(blob)
assert cur(0x200000 + ADDR_VAR, 4) == b'\0' * 4
assert cur(GET_HOOK, 4).hex() == 'c2e00901'                # b.movhi r23,0x48
assert cur(SET_HOOK, 4).hex() == 'c0e00901'                # b.movhi r7,0x48


# ---------------- stable read in its own cave (r3 = address already allowed) ----------------
rd_prog = [
 'rd_cave:',
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7), srli(R6, R3, 16), ori(R5, R0, 0x20), beq(R6, R5, 'rd_ram'),
 ori(R5, R0, 0x45), beq(R6, R5, 'rd_ram'),                            # RAM 0x45xxxx (only page 0x453C00 passes the check)
 ori(R5, R0, 0x48), beq(R6, R5, 'rd_ram'),                            # RAM 0x48xxxx (settings mirror and path record pages only)
 ori(R5, R0, 0x47), beq(R6, R5, 'rd_ram'),                            # RAM 0x47xxxx (DP receiver record pages only)
 ori(R5, R0, 0x3B), beq(R6, R5, 'rd_ram'),                            # RAM 0x3Bxxxx (window record pages only)
 ori(R7, R0, 0x11), ('bg.mfspr', {'D': R8, 'A': R7, '|': 0}),       # r8 = SR
 ('bt.movi', {'D': R5, 'I': -7}), andr(R6, R8, R5), ('bg.mtspr', {'A': R7, 'B': R6, '|': 0}),   # IEE/TEE off
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7), jal(RIU_RD), ('bn.or', {'D': R4, 'A': R3, 'B': R0}),
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7), jal(RIU_RD), bne(R3, R4, 'rd_uns'),
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7), jal(RIU_RD), bne(R3, R4, 'rd_uns'),
 ori(R7, R0, 0x11), ('bg.mtspr', {'A': R7, 'B': R8, '|': 0}),       # SR restored
 ori(R7, R0, 0xFF), andr(R4, R4, R7), j(L['g_ret']),
 'rd_ram:',                                                           # RAM 0x20/0x3B/0x45/0x47/0x48xxxx: plain byte load
 ('bg.lbz', {'?': R4, 'A': R3, '!': 0}), j(L['g_ret']),
 'rd_uns:',
 ori(R7, R0, 0x11), ('bg.mtspr', {'A': R7, 'B': R8, '|': 0}),
 ori(R4, R0, 0xFFFE), j(L['g_ret']),
]
rd_code, RL = S.assemble(rd_prog, RD_CAVE)
for a, b, x in A.disasm(rd_code, RD_CAVE, RD_CAVE + len(rd_code), RD_CAVE):
    lab = [k for k, v in RL.items() if v == a]
    print(('%-10s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
assert RD_CAVE + len(rd_code) <= 0x203D00
assert cur(RD_CAVE, len(rd_code)) == b'\0' * len(rd_code)

edits = [
 {'addr': '0x%06X' % CAVE, 'old': '00' * len(blob), 'new': blob.hex(),
  'asm': 'diag-poke handlers and allowlist checks (linker padding 0x203DC0); address variable at 0x203FF4'},
 {'addr': '0x%06X' % TABLES, 'old': '00' * len(tables), 'new': tables.hex(),
  'asm': 'diag-poke allowlist tables (image head zero area 0x201F00)'},
 {'addr': '0x%06X' % RD_CAVE, 'old': '00' * len(rd_code), 'new': rd_code.hex(),
  'asm': 'diag-poke stable read (linker padding 0x203C60): interrupts masked, three reads, 0xFFFE if they differ'},
 {'addr': '0x%06X' % GET_HOOK, 'old': cur(GET_HOOK, 4).hex(), 'new': S.encode('bg.j', {'/': L['get_hook']}, GET_HOOK).hex(),
  'asm': 'VCP GET unsupported-code path -> get_hook (0xEA/0xEB/0xEC)'},
 {'addr': '0x%06X' % SET_HOOK, 'old': cur(SET_HOOK, 4).hex(), 'new': S.encode('bg.j', {'/': L['set_hook']}, SET_HOOK).hex(),
  'asm': 'VCP SET unsupported-code path -> set_hook (0xEA/0xEB/0xEC)'},
]
patch = {
 'name': 'diag-poke',
 'summary': 'DIAGNOSTIC: read/write an allowlisted set of volatile pin and scaler registers over DDC (VCP 0xEA/0xEB address, 0xEC data)',
 'status': 'diagnostic, hardware test pending',
 'edits': edits,
 'notes': ("VCP 0xEA/0xEB set the register address (high/low 16 bits), VCP 0xEC reads (GET) or writes (SET, value <= 0xFF) "
           "one byte through the firmware's register helpers. Writes are limited to: %s. Reads are limited to the pages "
           "0x0003xx, 0x0004xx, 0x0005xx, 0x101Exx, 0x103Cxx, 0x103Dxx, RAM 0x2022xx-0x2024xx, 0x2039xx, 0x453Cxx, the settings mirror 0x4824xx-0x4825xx, the window records 0x3B49xx-0x3B4Bxx, the scaler DP receiver records 0x47F7xx-0x47F9xx and the input path records 0x4821xx-0x4823xx (plain load) and the scaler bank 0x102Fxx (any sub-bank), with interrupts masked and three agreeing reads; blocked reads return 0xFFFF, unstable reads (three reads differ) 0xFFFE. "
           "No EEPROM, flash, PM51 or factory-data access; all writes are volatile (power-cycle to undo). "
           "Generated by tools/patches_src_diag_poke.py." % ', '.join('0x%08X' % a for a in WRITE_OK)),
}
out = os.environ.get('OUT', 'diag-poke.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
