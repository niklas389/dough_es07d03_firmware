#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Source of patches/popup-round.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Rounded corners for the gray one-line popups of popup-flat.

- Four corner glyphs (12x18 px, 1 bpp, quarter circle of radius R) are loaded
  to codes 0x1C-0x1F together with the vendor's base glyph set (sub_253991
  loads set 0x32591C to codes 0-8 and 0x325C80 to 0xFE/0xFF; codes 0x09-0x18
  and 0x2A+ belong to other sets, 0x20+ to rendered text).
- After popup-flat has filled the window, the four corner cells get these
  glyphs with attribute 0x10: foreground 1 (the band gray) inside the curve,
  background 0 outside.

Assumption, not verified: palette index 0 is fully transparent (the vendor
fills unused menu areas with attribute 0x00). If it is not, the cut-off
corner pixels show colour 0 instead of the picture behind.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]
here = os.path.dirname(os.path.abspath(__file__))
flat = json.load(open(os.path.join(here, '..', 'patches', 'popup-flat.json')))
GRAY_DONE = int(flat['labels']['gray_done'], 16)

R = 6                               # corner radius in pixels
W, H = 12, 18                       # tile size
CODE0 = 0x1C                        # corner glyphs 0x1C TL, 0x1D TR, 0x1E BL, 0x1F BR
ATTR = 0x10                         # fg 1 (band gray), bg 0 (assumed transparent)
CAVE = 0x203D00
LOAD_HOOK = 0x2539C4                # sub_253991: jal sub_27BC9C (set 0x325C80 -> 0xFE)
GLYPH_LOAD = 0x27BC9C               # (first code, RLE data, count; 0 = until terminator)
ROW_WRITE = 0x25C8F5                # (col, row, code, count) with attribute 0x5389
ITEMS_DONE = 0x256D59
R0, R1, R3, R4, R5, R6, R7, R9, R12 = 0, 1, 3, 4, 5, 6, 7, 9, 12

def corner_rows():
    tl = []
    for y in range(H):
        bits = 0
        for x in range(W):
            inside = True
            if x < R and y < R:
                dx, dy = R - (x + 0.5), R - (y + 0.5)
                inside = dx * dx + dy * dy <= R * R
            if inside:
                bits |= 0x800 >> x
        tl.append(bits)
    mirror = lambda b: int(format(b, '012b')[::-1], 2)
    tr = [mirror(b) for b in tl]
    return [tl, tr, tl[::-1], tr[::-1]]

def rle(glyphs):
    words = []
    for g in glyphs:
        i = 0
        while i < len(g):
            n = 1
            while i + n < len(g) and g[i + n] == g[i] and n < 15:
                n += 1
            words.append(n << 12 | g[i])
            i += n
    words.append(0)
    return b''.join(w.to_bytes(2, 'little') for w in words)

glyphs = corner_rows()
for name, g in zip(('TL', 'TR', 'BL', 'BR'), glyphs):
    print(name)
    for b in g[:8] if name[0] == 'T' else g[-8:]:
        print('   ' + format(b, '012b').replace('0', '.').replace('1', '#'))
data = rle(glyphs)

ori = lambda rd, v: ('bg.ori', {'D': rd, 'A': R0, 't': v})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})

prog = [
 'load_corners:',                  # replaces jal sub_27BC9C(0xFE, 0x325C80, 0); args already set
 ('bt.addi', {'D': R1, 'I': -4}), ('bn.sw', {':': 0, 'A': R1, 'B': R9}),
 ('bg.jal', {'/': GLYPH_LOAD}),
 ori(R3, CODE0), ('bg.movhi', {'D': R4, 'U': 0x20}), ('bg.ori', {'D': R4, 'A': R4, 't': 0}),  # patched below
 ('bt.movi', {'D': R5, 'I': 0}),
 ('bg.jal', {'/': GLYPH_LOAD}),
 ('bn.lwz', {'D': R9, 'A': R1, ':': 0}), ('bt.addi', {'D': R1, 'I': 4}),
 ('bt.jr', {'A': R9}),
 'corners:',                       # from popup-flat gray_done; r12 = 0x3C0000
 ori(R7, ATTR), sb(0x5389, R12, R7),
 # top-left
 ('bt.movi', {'D': R3, 'I': 0}), ('bt.movi', {'D': R4, 'I': 0}), ori(R5, CODE0 + 0), ('bt.movi', {'D': R6, 'I': 1}),
 ('bg.jal', {'/': ROW_WRITE}),
 # top-right
 lbz(R3, 0x5386, R12), ('bt.addi', {'D': R3, 'I': -1}), ('bt.movi', {'D': R4, 'I': 0}), ori(R5, CODE0 + 1), ('bt.movi', {'D': R6, 'I': 1}),
 ('bg.jal', {'/': ROW_WRITE}),
 # bottom-left
 ('bt.movi', {'D': R3, 'I': 0}), lbz(R4, 0x5388, R12), ('bt.addi', {'D': R4, 'I': -1}), ori(R5, CODE0 + 2), ('bt.movi', {'D': R6, 'I': 1}),
 ('bg.jal', {'/': ROW_WRITE}),
 # bottom-right
 lbz(R3, 0x5386, R12), ('bt.addi', {'D': R3, 'I': -1}), lbz(R4, 0x5388, R12), ('bt.addi', {'D': R4, 'I': -1}),
 ori(R5, CODE0 + 3), ('bt.movi', {'D': R6, 'I': 1}),
 ('bg.jal', {'/': ROW_WRITE}),
 ('bg.j', {'/': ITEMS_DONE}),
 'glyphs:',
]
code, L = S.assemble(prog, CAVE)
gaddr = (CAVE + len(code) + 3) & ~3
# fix the data address (movhi 0x20 / ori low half)
code, L = S.assemble([p if not (isinstance(p, tuple) and p[0] == 'bg.ori' and p[1].get('D') == R4 and p[1].get('A') == R4)
                      else ('bg.ori', {'D': R4, 'A': R4, 't': gaddr & 0xFFFF}) for p in prog], CAVE)
assert (gaddr >> 16) == 0x20
blob = code + b'\0' * (gaddr - CAVE - len(code)) + data
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-14s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
print('glyph data at %#x, %d bytes' % (gaddr, len(data)))
assert CAVE + len(blob) <= 0x203FF0               # below panel-prepower flags
assert cur(CAVE, len(blob)) == b'\0' * len(blob)

lh_old = cur(LOAD_HOOK, 4)
x = A.decode(lh_old, 0, LOAD_HOOK)
assert x['name'] == 'bg.jal' and x['target'] == GLYPH_LOAD, x
assert cur(0x2539B7, 13).hex() == '5060fec0800641fc845c8098a0'    # r3=0xFE, r4=0x325C80, r5=0
gd_old = S.encode('bg.j', {'/': ITEMS_DONE}, GRAY_DONE)
edits = [
 {'addr': '0x%06X' % CAVE, 'old': '00' * len(blob), 'new': blob.hex(),
  'asm': 'load_corners / corners code and 4 corner glyphs (RLE) in linker padding 0x203D00'},
 {'addr': '0x%06X' % LOAD_HOOK, 'old': lh_old.hex(), 'new': S.encode('bg.jal', {'/': L['load_corners']}, LOAD_HOOK).hex(),
  'asm': 'sub_253991: jal sub_27BC9C -> jal load_corners (loads 0xFE set, then corners to 0x1C-0x1F)'},
 {'addr': '0x%06X' % GRAY_DONE, 'old': gd_old.hex(), 'new': S.encode('bg.j', {'/': L['corners']}, GRAY_DONE).hex(),
  'asm': 'popup-flat gray_done: j 0x256D59 -> j corners'},
]
patch = {
 'name': 'popup-round',
 'summary': 'Rounded corners (radius %d px) for the gray one-line OSD popups of popup-flat' % R,
 'status': 'experimental, hardware test pending',
 'requires': ['popup-flat'],
 'edits': edits,
 'notes': ("Loads four quarter-circle glyphs to codes 0x1C-0x1F whenever the vendor loads its base OSD glyph set "
           "(sub_253991) and draws them in the four corner cells of the gray popups with attribute 0x10 "
           "(foreground 1 = band gray, background 0). Assumes palette index 0 is transparent; if the corners show "
           "a colour instead, drop this patch. Generated by tools/patches_src_popup_round.py."),
}
out = os.environ.get('OUT', 'popup-round.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
