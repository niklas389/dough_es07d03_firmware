#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Source of patches/menu-round.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Rounded corners (radius 6 px) for the main OSD menu window, with the corner
glyphs of popup-round (1-bit codes 0x1C-0x1F, quarter circles, loaded with the
vendor base glyph set; this patch requires popup-round).

- The main menu window is 62 x 26 cells (window 0x3C538A, width 0x3C5386,
  height 0x3C5388; the one-line popups are 20-25 x 3). Its top row is the
  header band (blank tiles with attribute 0x24: background entry 4,
  0x2A2A2A), its bottom row the window background (attribute 0xFF: entry 15,
  0x0C0C0C).
- At both exits of the page draw sub_256C92 (0x256E42 tail jump to
  sub_256C31, epilogue at 0x256E4E), when the window is 62 x 26, the four
  corner cells get the corner glyphs through the vendor's row writer
  sub_25C8F5 (x, y, code, count) with attribute 0x40 at the top (inside =
  entry 4, the header band) and 0xF0 at the bottom (inside = entry 15),
  outside = entry 0 (transparent, as for popup-round). The attribute byte
  0x3C5389 is restored afterwards.
- A later partial redraw that rewrites a corner cell (none known: the
  information line ends well before the last column) would show a square
  corner until the next page draw.

Code in the image head zero area 0x2020A0 (after the TEL table, before the diag-log data at 0x202200).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

CAVE, CAVE_END = 0x2020A0, 0x2021F0
TAIL, TAIL_FN = 0x256E42, 0x256C31        # page draw exit 1: j sub_256C31 (epilogue already done)
EPI = 0x256E4E                            # page draw exit 2: epilogue (r16..r9 from 0..0x1C(r1), addi r1,0x20, jr r9)
ROW_WRITE = 0x25C8F5                      # (x, y, code, count), attribute 0x3C5389, window 0x3C538A
CODE0 = 0x1C                              # popup-round: TL, TR, BL, BR at 0x1C-0x1F
W, H = 62, 26
ATTR_TOP, ATTR_BOT = 0x40, 0xF0
R0, R1, R3, R4, R5, R6, R7, R9, R10 = 0, 1, 3, 4, 5, 6, 7, 9, 10

assert A.decode(d, TAIL - 0x200000, TAIL)['target'] == TAIL_FN and cur(TAIL - 3, 3).hex() == '1c2120'   # addi r1,r1,0x20
epi = cur(EPI, 0x1D)
assert epi.hex() == '0e01020de1060dc10a0da10e0d81120d61160d411a0d211e1c21208529', epi.hex()
assert cur(ROW_WRITE, 2).hex() == '8ae3'
assert cur(CAVE, CAVE_END - CAVE) == b'\0' * (CAVE_END - CAVE)
rr = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'patches', 'popup-round.json')))
assert any('0x1C-0x1F' in e['asm'] for e in rr['edits']), 'popup-round corner glyphs expected at 0x1C-0x1F'

mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
ori = lambda rd, ra, v: ('bg.ori', {'D': rd, 'A': ra, 't': v})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
nsw = lambda off, ra, rb: ('bn.sw', {':': off, 'A': ra, 'B': rb})
nlw = lambda rd, off, ra: ('bn.lwz', {'D': rd, 'A': ra, ':': off})
addi = lambda rd, ra, v: ('bn.addi', {'D': rd, 'A': ra, 'O': v})
def corner(x, y, k):
    return [ori(R3, R0, x), ori(R4, R0, y), ori(R5, R0, CODE0 + k), ori(R6, R0, 1), ('bg.jal', {'/': ROW_WRITE})]
prog = [
 'mr_tail:',                               # from 0x256E42 (r9 = caller of sub_256C92)
 addi(R1, R1, -4), nsw(0, R1, R9),
 ('bg.jal', {'/': 'mr_draw'}),
 nlw(R9, 0, R1), addi(R1, R1, 4),
 ('bg.j', {'/': TAIL_FN}),
 'mr_epi:',                                # from 0x256E4E: corners, then the vendor epilogue
 ('bg.jal', {'/': 'mr_draw'}),
 *[nlw(r, 4 * k, R1) for k, r in enumerate((16, 15, 14, 13, 12, 11, 10, 9))],
 addi(R1, R1, 0x20), ('bt.jr', {'A': R9}),
 'mr_draw:',                               # keeps r3 (return value) and the attribute byte
 addi(R1, R1, -12), nsw(0, R1, R9), nsw(4, R1, R3), nsw(8, R1, R10),
 mh(R7, 0x3C), lbz(R6, 0x5386, R7), ori(R5, R0, W), ('bg.bne', {'A': R6, 'B': R5, ';': 'mr_x'}),
 lbz(R6, 0x5388, R7), ori(R5, R0, H), ('bg.bne', {'A': R6, 'B': R5, ';': 'mr_x'}),
 lbz(R10, 0x5389, R7),
 ori(R6, R0, ATTR_TOP), sb(0x5389, R7, R6),
 *corner(0, 0, 0), *corner(W - 1, 0, 1),
 mh(R7, 0x3C), ori(R6, R0, ATTR_BOT), sb(0x5389, R7, R6),
 *corner(0, H - 1, 2), *corner(W - 1, H - 1, 3),
 mh(R7, 0x3C), sb(0x5389, R7, R10),
 'mr_x:',
 nlw(R10, 8, R1), nlw(R3, 4, R1), nlw(R9, 0, R1), addi(R1, R1, 12),
 ('bt.jr', {'A': R9}),
]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= CAVE_END, hex(CAVE + len(code))
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-9s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
# vendor epilogue order check: r16 at 0(r1) ... r9 at 0x1C(r1)
edits = [
 {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
  'asm': 'mr_tail / mr_epi / mr_draw (image head zero area 0x2020A0): corner glyphs in the 4 corner cells of the 62 x 26 menu window'},
 {'addr': '0x%06X' % TAIL, 'old': cur(TAIL, 4).hex(), 'new': S.encode('bg.j', {'/': L['mr_tail']}, TAIL).hex(),
  'asm': 'page draw sub_256C92 exit: j sub_256C31 -> j mr_tail'},
 {'addr': '0x%06X' % EPI, 'old': cur(EPI, 4).hex(), 'new': S.encode('bg.j', {'/': L['mr_epi']}, EPI).hex(),
  'asm': 'page draw sub_256C92 epilogue -> j mr_epi (corners, then the same epilogue)'},
]
patch = {
 'name': 'menu-round',
 'summary': 'Rounded corners (radius 6 px) for the main OSD menu window (corner glyphs of popup-round)',
 'status': 'untested (emulator-checked)',
 'requires': ['popup-round'],
 'edits': edits,
 'notes': 'See the docstring of tools/patches_src_menu_round.py. Generated by tools/patches_src_menu_round.py.',
}
out = os.environ.get('OUT', 'menu-round.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
