#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Source of patches/lang-latin.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

OSD language limited to English, Spanish, German and French. osd-aa-font
overwrites the Chinese/Japanese glyph set with the second bit plane of the
Latin font, so menus in Chinese or Japanese would be unreadable; osd-aa-font
requires this patch.

Language = settings +0x78 (order 0 English, 1 Chinese, 2 Spanish, 3 German,
4 French, 5 Japanese; docs/firmware-map.md section 56). Its writers:
- settings reset 0x262454 / 0x26262C and factory reset 0x26A434: 0 (kept);
- settings load 0x2631C9: values above 5 -> 0 (here also 1 and 5 -> 0, e.g.
  a language saved by the vendor firmware);
- menu confirm sub_265D2B (0x265D49): the list editor's choice 0x457857
  (here: 1 and 5 are ignored, as when the current language is chosen again;
  the list still shows the two entries);
- DDC/CI handler sub_26AD19 (0x26CC73): received value mod 6 (here: 1 and 5
  are ignored);
- profile restore sub_269AA4 (0x269F5B): the stored profile's language
  (here: 1 and 5 -> 0).

Code in the image head zero area 0x202180 (after menu-round, before the
diag-log data at 0x202200).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

CAVE, CAVE_END = 0x202180, 0x202200
MENU, MENU_STORE, MENU_SAME = 0x265D45, 0x265D49, 0x265D55     # beq r7,r5,same ; sb 0x78(r6),r7 ; epilogue (r3 = 0)
LOAD, LOAD_ZERO, LOAD_OK = 0x2631CC, 0x2631D0, 0x2631D7       # bleui r5,5,ok ; sb 0x78(r23),r0 ; next field
DDC, DDC_CONT = 0x26CC73, 0x26B341                             # sb 0x78(r4),r6 ; j 0x26B341
PROF, PROF_STORE = 0x269F57, 0x269F5B                          # lbz r7,0x64c(r7) ; sb 0x78(r5),r7
R0, R4, R5, R6, R7 = 0, 4, 5, 6, 7
CJK = (1, 5)

def ins(a): return A.decode(d, a - 0x200000, a)
assert ins(MENU)['name'] == 'bg.beq' and ins(MENU)['target'] == MENU_SAME and cur(MENU_STORE, 3).hex() == '18e678'
assert ins(0x265D40)['ops'] == 'r3,0x0' and ins(0x265D42)['ops'] == 'r5,0x78(r6)'
assert ins(LOAD)['name'] == 'bg.bleui' and ins(LOAD)['target'] == LOAD_OK and cur(LOAD_ZERO, 3).hex() == '181778'
assert ins(0x2631C9)['ops'] == 'r5,0x78(r23)' and ins(LOAD_OK)['ops'] == 'r7,0x87(r23)'
assert cur(DDC, 3).hex() == '18c478' and ins(DDC + 3)['target'] == DDC_CONT and ins(0x26CC68)['ops'] == 'r5,0x6'
assert ins(PROF)['ops'] == 'r7,0x64c(r7)' and cur(PROF_STORE, 3).hex() == '18e578'
assert cur(CAVE, CAVE_END - CAVE) == bytes(CAVE_END - CAVE)

j = lambda t: ('bg.j', {'/': t})
beq = lambda a, b, l: ('bg.beq', {'A': a, 'B': b, ';': l})
beqi = lambda a, i, l: ('bg.beqi', {'A': a, 'I': i, ';': l})
bgtu = lambda a, b, l: ('bg.bgtu', {'A': a, 'B': b, ';': l})
ori = lambda rd, ra, v: ('bg.ori', {'D': rd, 'A': ra, 't': v})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
prog = [
 'lg_menu:',                               # r7 = chosen, r5 = current, r3 = 0 ("no change")
 beq(R7, R5, 'lm_same'), beqi(R7, CJK[0], 'lm_same'), beqi(R7, CJK[1], 'lm_same'),
 j(MENU_STORE),
 'lm_same:', j(MENU_SAME),
 'lg_load:',                               # r5 = stored language, r23 = settings (r7 free)
 beqi(R5, CJK[0], 'll_zero'), beqi(R5, CJK[1], 'll_zero'),
 ori(R7, R0, 5), bgtu(R5, R7, 'll_zero'),
 j(LOAD_OK),
 'll_zero:', j(LOAD_ZERO),
 'lg_ddc:',                                # r6 = value mod 6, r4 = settings
 beqi(R6, CJK[0], 'ld_x'), beqi(R6, CJK[1], 'ld_x'),
 sb(0x78, R4, R6),
 'ld_x:', j(DDC_CONT),
 'lg_prof:',                               # r7 = profile entry address
 lbz(R7, 0x64C, R7),
 beqi(R7, CJK[0], 'lp_zero'), beqi(R7, CJK[1], 'lp_zero'),
 j(PROF_STORE),
 'lp_zero:', ori(R7, R0, 0), j(PROF_STORE),
]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= CAVE_END, hex(CAVE + len(code))
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-9s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
hook = lambda at, lab, n=4: S.encode('bg.j', {'/': L[lab]}, at).hex() + '00' * (n - 4)
edits = [
 {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
  'asm': 'lg_menu / lg_load / lg_ddc / lg_prof (image head zero area 0x202180): languages 1 (Chinese) and 5 (Japanese) refused'},
 {'addr': '0x%06X' % MENU, 'old': cur(MENU, 4).hex(), 'new': hook(MENU, 'lg_menu'),
  'asm': 'menu confirm sub_265D2B: beq (same language) -> j lg_menu (also ignores Chinese / Japanese)'},
 {'addr': '0x%06X' % LOAD, 'old': cur(LOAD, 4).hex(), 'new': hook(LOAD, 'lg_load'),
  'asm': 'settings load: language > 5 -> 0 becomes language > 5, 1 or 5 -> 0'},
 {'addr': '0x%06X' % DDC, 'old': cur(DDC, 7).hex(), 'new': hook(DDC, 'lg_ddc', 7),
  'asm': 'DDC/CI language set: sb 0x78(r4),r6 ; j 0x26B341 -> j lg_ddc (Chinese / Japanese ignored) ; 3-byte nop'},
 {'addr': '0x%06X' % PROF, 'old': cur(PROF, 4).hex(), 'new': hook(PROF, 'lg_prof'),
  'asm': 'profile restore: lbz r7,0x64c(r7) -> j lg_prof (Chinese / Japanese -> English)'},
]
patch = {
 'name': 'lang-latin',
 'summary': 'OSD language limited to English, Spanish, German and French (Chinese and Japanese are not readable with osd-aa-font)',
 'status': 'untested (emulator-checked)',
 'edits': edits,
 'notes': 'See the docstring of tools/patches_src_lang_latin.py. Generated by tools/patches_src_lang_latin.py.',
}
out = os.environ.get('OUT', 'lang-latin.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
