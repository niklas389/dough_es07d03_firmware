#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Source of patches/diag-fe.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

DIAGNOSTIC (requires diag-poke): ask the input front-end whether the link on
one connector is up, with the vendor's own two queries, and keep the answers
in RAM for tools/poke.sh.

  specctl set 0xED <code>       run the queries for connector code <code>
  specctl set 0xED <0x100|id>   raw mode (v2): skip 0x30/7 and send 0x60/0xB with index <id>
                                directly (e.g. 0x107 = USB-C, 0x108 = DP); 0x2024F0 then echoes <id>
  specctl set 0xED <0x300|n>    register mode (v3): read n (1-32) front-end register bytes from
                                the address set with diag-poke's VCP 0xEA/0xEB (tools/fereg.sh);
                                bytes at 0x202480.., 0x2024F2 = number of reads that completed
  tools/poke.sh read 0x2024F0   0x30/7 answer: the front-end's index for the code
  tools/poke.sh read 0x2024F1   0x60/0xB answer: 0 = source active, 1 = none (vendor gate: 0 refuses standby)
  tools/poke.sh read 0x2024F2   1 = the 0x60/0xB transaction completed, 0 = timeout/failed
  tools/poke.sh read 0x2024F3   the code that was queried
  tools/poke.sh read 0x2024F4   run counter (+1 per query, to see that it ran)
  tools/poke.sh read 0x2024F5   duration of the 0x30/7 transaction in ms (capped 255)
  tools/poke.sh read 0x2024F6   duration of the 0x60/0xB transaction in ms (capped 255)
  (durations need a diag-log variant in the build: they use its 1 ms counter at 0x202200;
   without it they read 0. Measured 2026-10-07: 2-6 ms after a mains start and after a
   deep-standby wake, also after writing PM 0x0393 = 0.)

Connector codes (table 0x3B427B, the values the vendor's standby gate uses):
port 0 USB-C = 8, port 1 DP = 7, port 2 HDMI 1 = 1, port 3 HDMI 2 = 3
(ports 4/5 = 4, 2; sub_268453 maps codes 1-9 at start-up).

Vendor use (docs/firmware-map.md section 24): the standby gate sub_2612F9
maps the current port's code with sub_23956D (command 0x30, sub 7, 1 byte
out, 1 byte back) and then sends that index with command 0x60, sub 0xB and
reads 1 byte back; non-zero refuses standby. It does so only for DP-class
ports (DP, USB-C). This diagnostic runs the same two transactions for any
code, to find out
  - whether the front-end answers for HDMI connectors at all, and
  - what it reports with an active source, with the output disabled while
    the link is held, and with nothing connected.

Context: DDC/CI SET commands are handled in the main loop (sub_26AD19 <-
0x20CF68 <- sub_20D134 <- main), the context of all other front-end
commands. Each mailbox phase waits up to 10 s; with a working front-end a
transaction takes 5-70 ms. A query the front-end does not answer blocks
the main loop for up to 10-20 s once (DDC replies and keys are delayed);
nothing is stored by the front-end for a query, and no setting changes.

Measured 2026-10-07 (docs/firmware-map.md section 27): the 0x30/7 answer is
not a fixed code -> index map. It was 0x08 for codes 7 and 8 while DP was the
selected input and 0x07 for both while USB-C was selected, i.e. the front-end
id of the selected DP-class connector; HDMI codes give 0. Raw mode asks the
link status of a connector that is not selected.

v3 register mode (2026-10-08, docs/firmware-map.md section 53): the
front-end's command 0xFF, sub 0xFF, x 2 (handler 0x87759 in its firmware)
reads one byte of its own register space (0x13EFC -> RIU read) at the 32-bit
address in the 4 data bytes (big-endian) and answers it. Only reads are
sent; sub 0xFF is fixed (sub 3 of the same command writes). Allowed ranges
(the DP receiver blocks; anything else is skipped and reads as 0, not
counted): 0x001100-0x0016FF (DPCD register banks of receivers 0-2, (rx <<
8) + 0x1100 / 0x1400), 0x110000-0x113FFF (receiver PHY/link banks, 0xA00
per receiver, and the stream timing (MSA) of the DP decoders at 0x113068 +
0x100 x decoder). Receiver 0 = USB-C (front-end id 7), 1 = DP (id 8).

Hooks: diag-poke's SET fall-through for unknown VCP codes (movhi r7,0x48;
j 0x26B335 inside diag-poke's cave) becomes j fe_set; fe_set handles 0xED
and otherwise runs the two replaced instructions. Code in the image head
zero area at 0x201C00 (copied to RAM by the boot loader, unused by the
firmware); results at 0x2024F0 (diag-poke read page 0x2024xx).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

HERE = os.path.dirname(os.path.abspath(__file__))
d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

CODE = 0x201C00
RES = 0x2024F0
VCP = 0xED
SET_CONT, SET_DONE = 0x26B335, 0x26AFC9
MAP_Q = 0x23956D                     # 0x30/7: r3 = code -> r3 = index (0 on failure)
MBOX = 0x238FA5                      # mailbox_query(r3 cmd, r4 sub, r5, r6 len, r7 data, r8 reply)
R0, R1, R3, R4, R5, R6, R7, R8, R23 = 0, 1, 3, 4, 5, 6, 7, 8, 23

# diag-poke's fall-through for unknown SET codes, located in its cave edit
dp = json.load(open(os.path.join(HERE, '..', 'patches', 'diag-poke.json')))
cave = next(e for e in dp['edits'] if e['addr'] == '0x203DC0')
cave_b, cave_a = bytes.fromhex(cave['new']), 0x203DC0
FALL = None
for a, b, x in A.disasm(cave_b, cave_a, cave_a + len(cave_b), cave_a):
    if x['mnem'] == 'b.movhi' and x['ops'] == 'r7,0x48':
        y = A.decode(cave_b, a - cave_a + x['len'], a + x['len'])
        if y['mnem'] == 'b.j' and y.get('target') == SET_CONT:
            FALL = a
assert FALL is not None, 'diag-poke SET fall-through not found'
fall_old = cave_b[FALL - cave_a:FALL - cave_a + 4]

mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
ori = lambda rd, ra, v: ('bg.ori', {'D': rd, 'A': ra, 't': v})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
lhz = lambda rd, off, ra: ('bg.lhz', {'D': rd, 'A': ra, 'X': off})
movi = lambda r, i: ('bt.movi', {'D': r, 'I': i})
lo = RES & 0xFFFF

T = 0x2200                           # diag-log ms counter (u32 at 0x202200)
ADDR_VAR = 0x3FF4                    # diag-poke's address variable (u32 at 0x203FF4, VCP 0xEA/0xEB)
BUF = 0x202480                       # v3 register mode: up to 32 bytes (page 0x2024xx, unused)
NMAX = 32
R10, R11, R12, R13 = 10, 11, 12, 13
TS = lo + 8                          # u32 scratch: start time (0x2024F8)

def dur(dst, tag=''):                # byte at 0x20xxxx dst = min(now - start, 255); start = now
    lab = 'd_%x%s' % (dst, tag)      # unique label per use
    return [mh(R7, 0x20), ('bg.lwz', {'D': R5, 'A': R7, 'W': T}), ('bg.lwz', {'D': R6, 'A': R7, 'W': TS}),
            ('bg.sw', {'W': TS, 'A': R7, 'B': R5}),
            ('bn.sub', {'D': R6, 'A': R5, 'B': R6}),
            ('bg.sfgtui', {'A': R6, 'Y': 255}), ('bg.bnf', {"'": lab}), ori(R6, R0, 255),
            lab + ':', sb(dst, R7, R6)]

prog = [
 'fe_set:',
 ori(R7, R0, VCP), ('bg.beq', {'A': R6, 'B': R7, ';': 'fe_go'}),
 mh(R7, 0x48), ('bg.j', {'/': SET_CONT}),                  # replaced instructions (diag-poke fall-through)
 'fe_go:',
 mh(R7, 0x45), lhz(R3, 0x3C84, R7),                       # r3 = connector code (VCP value)
 mh(R7, 0x20), sb(lo + 3, R7, R3),                        # echo the code
 sb(lo, R7, R0), sb(lo + 1, R7, R0), sb(lo + 2, R7, R0),   # clear old answers
 lbz(R6, lo + 4, R7), ('bt.addi', {'D': R6, 'I': 1}), sb(lo + 4, R7, R6),   # run counter
 ('bg.lwz', {'D': R5, 'A': R7, 'W': T}), ('bg.sw', {'W': TS, 'A': R7, 'B': R5}),        # start time
 ('bn.srli', {'D': R4, 'A': R3, 'H': 8}),                   # value >= 0x100: raw mode, index = low byte
 ('bg.beqi', {'A': R4, 'I': 0, ';': 'fe_map'}),
 ('bg.beqi', {'A': R4, 'I': 3, ';': 'fe_reg'}),             # 0x3nn: register mode
 ('bn.andi', {'D': R3, 'A': R3, 'N': 0xFF}), ('bg.j', {'/': 'fe_idx'}),
 'fe_map:',
 ('bg.jal', {'/': MAP_Q}),                                # r3 = front-end index
 'fe_idx:',
 mh(R7, 0x20), sb(lo, R7, R3),
 ('bt.addi', {'D': R1, 'I': -4}), ('bn.sw', {':': 0, 'A': R1, 'B': R3}),
 *dur(lo + 5),
 ('bn.lwz', {'D': R3, 'A': R1, ':': 0}), ('bt.addi', {'D': R1, 'I': 4}),
 ('bt.addi', {'D': R1, 'I': -8}),
 sb(6, R1, R3), sb(7, R1, R0),                            # data byte, reply byte
 ori(R3, R0, 0x60), ori(R4, R0, 0xFF), movi(R5, 0xB), movi(R6, 1),
 ('bn.addi', {'D': R7, 'A': R1, 'O': 6}), ('bn.addi', {'D': R8, 'A': R1, 'O': 7}),
 ('bg.jal', {'/': MBOX}),                                 # r3 = 1 ok / 0 failed
 lbz(R4, 7, R1),
 ('bt.addi', {'D': R1, 'I': 8}),
 mh(R7, 0x20), sb(lo + 1, R7, R4), sb(lo + 2, R7, R3),
 *dur(lo + 6),
 ('bg.j', {'/': SET_DONE}),

 # ---- v3 register mode: r3 = 0x3nn -> n front-end register bytes from the address at 0x203FF4 ----
 'fe_reg:',
 ('bn.andi', {'D': R4, 'A': R3, 'N': 0xFF}),
 ('bg.bnei', {'A': R4, 'I': 0, ';': 'fr_n1'}), movi(R4, 1),
 'fr_n1:',
 ('bg.sfgtui', {'A': R4, 'Y': NMAX}), ('bg.bnf', {"'": 'fr_n2'}), ori(R4, R0, NMAX),   # n > 32 -> 32
 'fr_n2:',
 ('bn.addi', {'D': R1, 'A': R1, 'O': -24}),
 ('bn.sw', {':': 8, 'A': R1, 'B': R10}), ('bn.sw', {':': 12, 'A': R1, 'B': R11}),
 ('bn.sw', {':': 16, 'A': R1, 'B': R12}), ('bn.sw', {':': 20, 'A': R1, 'B': R13}),
 ('bn.or', {'D': R10, 'A': R4, 'B': R0}), movi(R11, 0), movi(R13, 0),
 mh(R7, 0x20), ('bg.lwz', {'D': R12, 'A': R7, 'W': ADDR_VAR}),
 'fr_l:',
 ('bn.add', {'D': R7, 'A': R12, 'B': R11}),                # address of this byte
 sb(4, R1, R0),                                           # answer byte (0 when skipped / failed)
 ('bn.srli', {'D': R6, 'A': R7, 'H': 8}),                   # allowed: 0x0011xx-0x0016xx ...
 ('bn.addi', {'D': R6, 'A': R6, 'O': -0x11}), ('bg.bleui', {'A': R6, 'I': 5, ';': 'fr_ok'}),
 ('bn.srli', {'D': R6, 'A': R7, 'H': 14}),                  # ... or 0x110000-0x113FFF
 ori(R5, R0, 0x44), ('bg.bne', {'A': R6, 'B': R5, ';': 'fr_st'}),
 'fr_ok:',
 ('bn.srli', {'D': R6, 'A': R7, 'H': 24}), sb(0, R1, R6),   # data: 32-bit address, big-endian
 ('bn.srli', {'D': R6, 'A': R7, 'H': 16}), sb(1, R1, R6),
 ('bn.srli', {'D': R6, 'A': R7, 'H': 8}), sb(2, R1, R6),
 sb(3, R1, R7),
 ori(R3, R0, 0xFF), ori(R4, R0, 0xFF), movi(R5, 2), movi(R6, 4),   # front-end debug read (cmd 0xFF, sub 0xFF, x 2)
 ('bn.or', {'D': R7, 'A': R1, 'B': R0}), ('bn.addi', {'D': R8, 'A': R1, 'O': 4}),
 ('bg.jal', {'/': MBOX}),
 ('bg.beqi', {'A': R3, 'I': 0, ';': 'fr_st'}),
 ('bn.addi', {'D': R13, 'A': R13, 'O': 1}),
 'fr_st:',
 lbz(R4, 4, R1),
 mh(R7, 0x20), ('bg.addi', {'D': R7, 'A': R7, 'Y': BUF & 0xFFFF}), ('bn.add', {'D': R7, 'A': R7, 'B': R11}),
 ('bn.sb', {'z': 0, 'A': R7, 'B': R4}),
 ('bn.addi', {'D': R11, 'A': R11, 'O': 1}),
 ('bg.bne', {'A': R11, 'B': R10, ';': 'fr_l'}),
 mh(R7, 0x20), sb(lo + 2, R7, R13),                       # reads that completed
 *dur(lo + 6, '_r'),
 ('bn.lwz', {'D': R13, 'A': R1, ':': 20}), ('bn.lwz', {'D': R12, 'A': R1, ':': 16}),
 ('bn.lwz', {'D': R11, 'A': R1, ':': 12}), ('bn.lwz', {'D': R10, 'A': R1, ':': 8}),
 ('bn.addi', {'D': R1, 'A': R1, 'O': 24}),
 ('bg.j', {'/': SET_DONE}),
]
labels = [x for x in prog if isinstance(x, str)]
assert len(labels) == len(set(labels)), 'duplicate labels'
code, L = S.assemble(prog, CODE)
for a, b, x in A.disasm(code, CODE, CODE + len(code), CODE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-8s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
assert CODE + len(code) <= 0x201F00                       # diag-poke allowlist tables from 0x201F00
assert cur(CODE, len(code)) == b'\0' * len(code)
assert cur(RES, 12) == b'\0' * 12
assert cur(BUF, NMAX) == b'\0' * NMAX
# vendor code the routine relies on
assert cur(MAP_Q, 3).hex() == '1c21ec'                     # sub_23956D: addi r1,r1,-0x14
assert A.decode(d, 0x239579 - 0x200000, 0x239579)['ops'] == 'r3,r0,0x30'
assert cur(MBOX, 3).hex() == '1c21d4'                      # mailbox_query: addi r1,r1,-0x2c
assert A.decode(d, 0x261344 - 0x200000, 0x261344)['ops'] == 'r3,r0,0x60'   # vendor gate: same 0x60 / 0xff / 0xb query
assert A.decode(d, 0x26134A - 0x200000, 0x26134A)['ops'] == 'r5,0xb'

hook = S.encode('bg.j', {'/': CODE}, FALL)
assert len(hook) == 4
print('fall-through at %#x: %s -> %s' % (FALL, fall_old.hex(), hook.hex()))

patch = {
 'name': 'diag-fe',
 'summary': 'DIAGNOSTIC: VCP 0xED = connector code runs the front-end link query (0x30/7, 0x60/0xB, as the vendor standby gate; 0x100|id: 0x60/0xB for front-end id directly; 0x300|n: read n front-end DP receiver register bytes at the diag-poke address) and keeps the answers at RAM 0x2024F0 / 0x202480 for tools/poke.sh',
 'status': 'diagnostic; v2 link query hardware-tested 2026-10-08; v3 register mode untested',
 'requires': ['diag-poke'],
 'edits': [
  {'addr': '0x%06X' % CODE, 'old': '00' * len(code), 'new': code.hex(),
   'asm': 'fe_set (image head zero area 0x201C00): VCP 0xED -> sub_23956D(code), mailbox 0x60/0xB; results at 0x%06X' % RES},
  {'addr': '0x%06X' % FALL, 'old': fall_old.hex(), 'new': hook.hex(),
   'asm': 'diag-poke SET fall-through (movhi r7,0x48) -> j fe_set'},
 ],
 'notes': ("Results: 0x2024F0 front-end index (0x30/7 answer), 0x2024F1 link status (0x60/0xB answer), 0x2024F2 1 = the "
           "0x60/0xB transaction completed, 0x2024F3 queried code, 0x2024F4 run counter, 0x2024F5/F6 durations of the two transactions in ms (needs a diag-log variant). Codes: USB-C 8, DP 7, HDMI 1 = 1, "
           "HDMI 2 = 3. Raw mode: value 0x100 | front-end id (USB-C 7, DP 8, HDMI 0x0B/0x0C) skips 0x30/7. Runs only on a SET of VCP 0xED; a query the front-end does not answer can block the main loop for "
           "up to 10-20 s once. Generated by tools/patches_src_diag_fe.py."),
}
out = os.environ.get('OUT', 'diag-fe.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
