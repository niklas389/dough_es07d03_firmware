#!/usr/bin/env python3
"""Source of patches/popup-flat.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

The small OSD popups (OSD states 2-5, 8, 9, 0x0C, 0x19; frame code in sub_256C92)
are a tile window filled with attribute 0xFF (near-black, the message area).
For all of them the vendor then paints row 0 with attribute 0x11 (see-through
dark gray) and row 1 with glyph 2 (top half background, bottom half foreground)
in attribute 0xF1: the header band of the full menu frame. Except for state
0x19, no popup draws anything into that band. Attribute byte = fg << 4 | bg.

This patch draws the one-line popups as a single see-through gray box with
white text, centred:
- states 2/4 ("No signal", power-on; 25x3) and 8/9/0x0C (input name etc.;
  20x4 -> 20x3): whole window attribute 0x11 (the band colour), message
  attribute 0x2F -> 0x21 (white on band colour, as state 0x19 uses for its
  title), message row 2 -> 1;
- states 3/5 (multi-line texts with colours for the dark body): no band,
  near-black body as before;
- state 0x19 (title in the band): unchanged.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

CAVE = 0x203C00                    # linker padding; other caves end below 0x203B10
HOOK = 0x256FEB                    # b.ori r7,r0,0x11 / b.sb 0x5389(r12),r7 (header row attribute)
ITEMS_DONE = 0x256D59              # sub_256C92: continue with the page items
AFTER_SB = 0x256FF2                # instruction after the replaced b.sb
FILL = 0x25C254                    # (col, row, cols, rows): fill rectangle with attribute 0x5389, code 0
R0, R3, R4, R5, R6, R7, R12 = 0, 3, 4, 5, 6, 7, 12
STATES, STATE_SZ = 0x3BAAFC, 0x1C
BAND, TEXT_OLD, TEXT_NEW = 0x11, 0x2F, 0x21

ori = lambda rd, v: ('bg.ori', {'D': rd, 'A': R0, 't': v})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
beq = lambda a, b, lab: ('bg.beq', {'A': a, 'B': b, ';': lab})

prog = [
 'popup_rows:',                    # r6 = OSD state, r12 = 0x3C0000
 ori(R7, 0x19), beq(R6, R7, 'keep'),
 ori(R7, 3), beq(R6, R7, 'done'),
 ori(R7, 5), beq(R6, R7, 'done'),
 ori(R7, BAND), sb(0x5389, R12, R7),
 ('bt.movi', {'D': R3, 'I': 0}), ('bt.movi', {'D': R4, 'I': 0}),
 lbz(R5, 0x5386, R12), lbz(R6, 0x5388, R12),     # window columns / rows
 ('bg.jal', {'/': FILL}),
 'gray_done:',                     # popup-round redirects this jump
 ('bg.j', {'/': ITEMS_DONE}),
 'keep:',                          # state 0x19 draws its title in row 0: stock
 ori(R7, BAND), sb(0x5389, R12, R7),
 ('bg.j', {'/': AFTER_SB}),
 'done:',
 ('bg.j', {'/': ITEMS_DONE}),
]
code, L = S.assemble(prog, CAVE)
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-12s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
assert CAVE + len(code) <= 0x203D00
assert cur(CAVE, len(code)) == b'\0' * len(code)
assert cur(HOOK, 7).hex() == '50e011f8ec5389', cur(HOOK, 7).hex()

hook = S.encode('bg.j', {'/': CAVE}, HOOK)
edits = [
 {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
  'asm': 'popup_rows (linker padding 0x203C00): state 0x19 stock; 3/5 no band; others whole window attribute 0x11'},
 {'addr': '0x%06X' % HOOK, 'old': cur(HOOK, 4).hex(), 'new': hook.hex(),
  'asm': 'b.ori r7,r0,0x11 (+1st byte of b.sb) -> b.j popup_rows; the rest of the b.sb is never reached'},
]

def byte_edit(addr, old, new, why):
    assert cur(addr, 1)[0] == old, (hex(addr), cur(addr, 1).hex())
    edits.append({'addr': '0x%06X' % addr, 'old': '%02x' % old, 'new': '%02x' % new, 'asm': why})

def page_of(state):
    return int.from_bytes(cur(STATES + state * STATE_SZ + 8, 4), 'little')

assert page_of(2) == page_of(4)
for st in (4, 8, 9, 0x0C):           # state 2 shares the page of state 4
    pg = page_of(st)
    assert cur(STATES + st * STATE_SZ + 0x0C, 1)[0] == 1          # one item
    assert cur(pg, 2) == b'\x00\x02' and cur(pg + 7, 1)[0] & 0x08  # col 0, row 2, centred text
    assert cur(pg + 0x28, 4) == b'\0\0\0\0'                         # no item flags
    byte_edit(pg + 1, 2, 1, 'OSD state %X page %X: message item row 2 -> 1' % (st, pg))
    byte_edit(pg + 4, TEXT_OLD, TEXT_NEW, 'OSD state %X: message attribute 0x2F -> 0x21 (white on band gray)' % st)
    byte_edit(pg + 5, TEXT_OLD, TEXT_NEW, 'OSD state %X: message attribute (selected) 0x2F -> 0x21' % st)
for st in (8, 9, 0x0C):
    byte_edit(STATES + st * STATE_SZ + 1, 4, 3, 'OSD state %X: window 4 -> 3 rows' % st)

patch = {
 'name': 'popup-flat',
 'summary': 'One-line OSD popups (No signal, input name, ...) as one see-through gray box with white centred text, without the empty header band',
 'status': 'experimental, hardware test pending',
 'edits': edits,
 'notes': ("sub_256C92 paints rows 0/1 of every small popup with the menu header band (attribute 0x11 and the "
           "half-tile glyph 2) although only state 0x19 places text there. For the one-line popups (states 2/4, "
           "8/9/0x0C) the patch fills the whole window with the band colour (0x11), draws the message as white on "
           "that colour (0x21) and moves it to the middle row (input popups 20x4 -> 20x3). States 3/5 keep the "
           "near-black body without the band; state 0x19 is unchanged. Cosmetic only. "
           "popup-round hooks the jump at label gray_done (%#x). Generated by tools/patches_src_popup_flat.py."
           % L['gray_done']),
 'labels': {'gray_done': '0x%06X' % L['gray_done']},
}
out = os.environ.get('OUT', 'popup-flat.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
