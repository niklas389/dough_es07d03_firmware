#!/usr/bin/env python3
"""Source of patches/osd-aa-font.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Anti-aliased OSD text: the menu text is rendered into 2-bit (4-level) glyphs
with Noto Sans Condensed SemiBold 14 px instead of the 1-bit vendor font
(docs/firmware-map.md section 56).

  FONT=NotoSans-CondensedSemiBold.ttf RT=runtime_0x200000.bin OUT=patches/osd-aa-font.json \\
      python3 tools/patches_src_osd_aa.py
  (hinted TTF: https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io/fonts/NotoSans/hinted/ttf/
   NotoSans-CondensedSemiBold.ttf; SIL Open Font License 1.1, see docs/licenses/NotoSans-OFL.txt)

How it works:
- Font data: font set 0 (0x3BB068, 40-byte records) keeps the vendor record format
  and holds bit 0 of each pixel (plane A); the records of font set 1 (0x3BD868,
  vendor Chinese/Japanese glyphs) hold bit 1 (plane B) for codes 0x00-0x7D. Latin
  codes get Noto Sans glyphs (header: no left blank, width = rounded Noto advance,
  coverage -> 4 levels); the other set-0 codes below 0x7E keep the vendor bitmap
  in both planes (full intensity), e.g. the CJK language names.
  Chinese and Japanese text is not readable with this patch (their set-1 glyphs
  are overwritten).
- Renderer 0x27C046: its tile helpers keep a second (shadow) tile buffer for plane
  B: blit 0x27BF05, clear 0x27BEF3, vertical shift 0x27BE4D, merge 0x27C257 and
  flush 0x27BFCF are redirected. The flush writes each 12 x 18 tile as a 2-bit
  glyph (54 bytes, mode 3) to its own RAM address instead of relying on the
  auto-increment of 1-bit glyphs.
- Code map: a rendered tile of logical code L = (bank 0x457888 << 8) + slot goes to
  the 2-bit code P: L 0x020-0x163 -> 2L + 0x38 (0x078-0x2FF), L 0x164-0x194 ->
  2L + 0x48 (0x310-0x371), L 0x1C0-0x1D9 -> 2L + 0x4A (0x3CA-0x3FD); the vendor
  2-bit icons stay at 0x300-0x30F and 0x372-0x3C9. Other L are not text.
- 2-bit range start 0x101C0A: 0x300 -> 0x078 (0x253A6B). The vendor 1-bit sets
  stay below (base glyphs 0-8, overlay and crosshair sets 0x00-0x77, popup-round
  corners 0x1C-0x1F); the two half-circle glyphs move from 0xFE/0xFF to 0x20/0x21
  (0x2539B7, 0x254EDF, 0x254EED).
- Text placement 0x25CA96 (all item strings): attributes and codes of text tiles are
  rewritten (0x25CB21 -> place2): code P per tile; attribute fg nibble -> a palette
  group of its own. A 2-bit tile shows palette entry 16 x fg + value, so each text
  attribute (fg colour f, bg colour b of the 1-bit palette) gets a free group
  (6, 7, 8, 9, B, C, D, E, F, 3, 4, 5; first come first served) loaded with
  [b, (2b + f) / 3, (b + 2f) / 3, f].
- Palette loader 0x2533CE (sel 0) is hooked: it records palette entries 0-15
  (the 1-bit colours) and reloads all text groups after every load.
- Letter spacing: the renderer adds (mode byte 0x3CB81C & 3) blank columns after
  each glyph (1 for text, 2 for numbers and values); the Noto widths include the
  side bearings, so the seven reads of it in the renderer are changed to & 0.
Code and RAM in the image head zero area (code 0x203000, RAM 0x202D00-0x202EAF).
Checked in an emulator with tools/osd_emu_check.py (section 56).
"""
import sys, json, os, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]
def u16(a): return int.from_bytes(cur(a, 2), 'little')
def u32(a): return int.from_bytes(cur(a, 4), 'little')

# ---------------------------------------------------------------- addresses
CODE = 0x203000                      # code (image head zero area, below the linker padding users at 0x203800)
CODE_END = 0x203800
RAM = 0x202D00                       # RAM variables (zero at boot)
SH = RAM + 0x00                      # shadow tile buffers: plane B of buffer A (r1+0x28) and B (r1+0x4C), 0x48 bytes
CUR_B, CUR_S = RAM + 0x48, RAM + 0x49   # bank and slot of the next flushed tile
PAL16 = RAM + 0x50                   # palette entries 0-15, 3 bytes each (table bytes 0-2)
TMAP = RAM + 0x80                    # attribute -> group + 1 (0 = not assigned), 256 bytes
GATTR = RAM + 0x180                  # per assigned group (pool order): its attribute
NGRP = RAM + 0x190                   # number of assigned groups
PTAB = RAM + 0x1A0                   # 4-entry palette table for one group (R, G, B, flag)
RAM_END = RAM + 0x1B0
POOL = [6, 7, 8, 9, 0xB, 0xC, 0xD, 0xE, 0xF, 3, 4, 5]

FONT_TAB = 0x3BB068                  # font set 0 (pointer 0x453DE8)
PB_OFF = 0x2800                      # plane B = set-1 record of the same code
PB_CODES = 0x7E                      # codes 0x00-0x7D have a plane B
RENDER_START = 0x27C091              # jal 0x25D952 (font RAM address of the first code)
ADDR_SET = 0x25D952
BLIT, CLEAR, VSHIFT, VSHIFT_END = 0x27BF05, 0x27BEF3, 0x27BE4D, 0x27BEF3
MERGE, MERGE_CONT, FLUSH = 0x27C257, 0x27C273, 0x27BFCF
PLACE, PLACE_RET = 0x25CB21, 0x25CAC3
PAL, PAL_CONT = 0x2533CE, 0x2533D4
RANGE_SET = 0x253A6B                 # ori r4,r0,0x300 (2-bit range start for 0x23C24F(0, r4))
HALF_LOAD, HALF_PUT1, HALF_PUT2 = 0x2539B7, 0x254EDF, 0x254EED
RIU_WR, WMASK, W16 = 0x23D9E7, 0x23DC0F, 0x23DBE4
PORT, MODE, CODEHI = 0x101C66, 0x101C68, 0x101C67
TWO_BIT_START = 0x78
SPACING = [0x27BF47, 0x27C1AB, 0x27C218, 0x27C329, 0x27C388, 0x27C61D, 0x27C63D]   # andi rX,rY,0x3 (letter spacing, mode byte 0x3CB81C bits 0-1)
HALF_CODE = 0x20

R0, R1, R3, R4, R5, R6, R7, R9 = 0, 1, 3, 4, 5, 6, 7, 9
R10, R11, R12, R13, R14, R15, R16, R22 = 10, 11, 12, 13, 14, 15, 16, 22
R23, R24, R25, R26 = 23, 24, 25, 26

# ---------------------------------------------------------------- instruction helpers
mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
ori = lambda rd, ra, v: ('bg.ori', {'D': rd, 'A': ra, 't': v})
andi = lambda rd, ra, v: ('bg.andi', {'D': rd, 'A': ra, 't': v})
addi = lambda rd, ra, v: ('bg.addi', {'D': rd, 'A': ra, 'Y': v})
muli = lambda rd, ra, v: ('bg.muli', {'D': rd, 'A': ra, 'Y': v})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
lhz = lambda rd, off, ra: ('bg.lhz', {'D': rd, 'A': ra, 'X': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
sh = lambda off, ra, rb: ('bg.sh', {'X': off, 'A': ra, 'B': rb})
sw = lambda off, ra, rb: ('bg.sw', {'W': off, 'A': ra, 'B': rb})
lw = lambda rd, off, ra: ('bg.lwz', {'D': rd, 'A': ra, 'W': off})
add = lambda rd, ra, rb: ('bn.add', {'D': rd, 'A': ra, 'B': rb})
sub = lambda rd, ra, rb: ('bn.sub', {'D': rd, 'A': ra, 'B': rb})
orr = lambda rd, ra, rb: ('bn.or', {'D': rd, 'A': ra, 'B': rb})
mov = lambda rd, ra: ('bn.or', {'D': rd, 'A': ra, 'B': R0})
sll = lambda rd, ra, rb: ('bn.sll', {'D': rd, 'A': ra, 'B': rb})
srl = lambda rd, ra, rb: ('bn.srl', {'D': rd, 'A': ra, 'B': rb})
slli = lambda rd, ra, n: ('bn.slli', {'D': rd, 'A': ra, 'H': n})
srli = lambda rd, ra, n: ('bn.srli', {'D': rd, 'A': ra, 'H': n})
extbz = lambda rd, ra: ('bn.extbz', {'D': rd, 'A': ra})
extbs = lambda rd, ra: ('bn.extbs', {'D': rd, 'A': ra})
beqi = lambda a, i, l: ('bg.beqi', {'A': a, 'I': i, ';': l})
bnei = lambda a, i, l: ('bg.bnei', {'A': a, 'I': i, ';': l})
bgtsi = lambda a, i, l: ('bg.bgtsi', {'A': a, 'I': i, ';': l})
blesi = lambda a, i, l: ('bg.blesi', {'A': a, 'I': i, ';': l})
beq = lambda a, b, l: ('bg.beq', {'A': a, 'B': b, ';': l})
bne = lambda a, b, l: ('bg.bne', {'A': a, 'B': b, ';': l})
bgtu = lambda a, b, l: ('bg.bgtu', {'A': a, 'B': b, ';': l})
bleu = lambda a, b, l: ('bg.bleu', {'A': a, 'B': b, ';': l})
sfnei = lambda a, v: ('bn.sfnei', {'A': a, 'O': v})
bf = lambda l: ('bn.bf', {'~': l})
j = lambda t: ('bg.j', {'/': t})
jal = lambda t: ('bg.jal', {'/': t})
jr = lambda r: ('bt.jr', {'A': r})
def const32(r, v): return [mh(r, v >> 16), ori(r, r, v & 0xFFFF)]
def ram(r): return [mh(r, RAM >> 16)]                     # r = 0x200000; RAM offsets below 0x8000
lo = lambda a: a & 0xFFFF
assert RAM >> 16 == 0x20 and (RAM_END & 0xFFFF) < 0x8000
def call(fn, *args):                 # args: ('c', const) or ('r', reg), into r3, r4, ...
    out = []
    for k, (t, v) in enumerate(args):
        out += const32(3 + k, v) if t == 'c' else [mov(3 + k, v)]
    return out + [jal(fn)]
def frame(regs):                     # save r9 + regs; returns (prologue, epilogue)
    rs = [R9] + regs
    n = 4 * len(rs)
    pro = [addi(R1, R1, -n)] + [sw(4 * k, R1, r) for k, r in enumerate(rs)]
    epi = [lw(r, 4 * k, R1) for k, r in enumerate(rs)] + [addi(R1, R1, n)]
    return pro, epi
SHADOW = lambda rd, rb: [sub(rd, rb, R1), *const32(R7, SH - 0x28), add(rd, rd, R7)]   # rd = shadow of buffer rb (r7 clobbered)

# ---------------------------------------------------------------- code
vbody = cur(VSHIFT, VSHIFT_END - VSHIFT)          # vendor vertical shift, copied unchanged (PC-relative branches stay inside)
for a, b, x in A.disasm(vbody, VSHIFT, VSHIFT_END, VSHIFT):
    if 'target' in x and x['target'] is not None:
        assert VSHIFT <= x['target'] < VSHIFT_END, (hex(a), x)
    assert x['mnem'] not in ('b.jal', 'b.jalr'), x

f_pro, f_epi = frame([R10, R11, R12, R13, R14])
g_pro, g_epi = frame([R10, R11])
s_pro, s_epi = frame([R10, R11, R12])
h_pro, h_epi = frame([R10, R11, R12, R13])

prog = [
 # ---- renderer start (jal from 0x27C091, r3 = first slot): remember bank and slot, then the vendor set-up
 'start2:',
 mh(R7, 0x45), lbz(R6, 0x7888, R7),
 *ram(R7), sb(lo(CUR_B), R7, R6), sb(lo(CUR_S), R7, R3),
 j(ADDR_SET),
 # ---- clear (r3 = tile buffer): vendor buffer and its shadow; r6, r7, r23 only
 'clear2:',
 *SHADOW(R23, R3),
 ('bt.movi', {'D': R6, 'I': 0}),
 'cl_loop:',
 add(R7, R3, R6), sh(0, R7, R0),
 add(R7, R23, R6), sh(0, R7, R0),
 addi(R6, R6, 2), sfnei(R6, 0x24), bf('cl_loop'),
 jr(R9),
 # ---- blit (r3 = dst buffer, r4 = glyph rows, r5 = left shift, r6 = columns): both planes
 'blit2:',
 ('bt.movi', {'D': R7, 'I': 12}), sub(R23, R7, R6), extbz(R23, R23),
 *SHADOW(R25, R3),
 mov(R26, R4),
 *const32(R7, FONT_TAB + 2), sub(R7, R4, R7), ori(R6, R0, PB_CODES * 40),
 bleu(R6, R7, 'bl_go'),                                   # outside set-0 codes 0-0x7D: plane B = plane A
 addi(R26, R4, PB_OFF),
 'bl_go:',
 ('bt.movi', {'D': R6, 'I': 0}),
 'bl_loop:',
 add(R7, R4, R6), lhz(R7, 0, R7), sll(R7, R7, R5), andi(R7, R7, 0xFFF), srl(R7, R7, R23),
 lhz(R24, 0, R3), orr(R7, R7, R24), sh(0, R3, R7),
 add(R7, R26, R6), lhz(R7, 0, R7), sll(R7, R7, R5), andi(R7, R7, 0xFFF), srl(R7, R7, R23),
 lhz(R24, 0, R25), orr(R7, R7, R24), sh(0, R25, R7),
 addi(R6, R6, 2), addi(R3, R3, 2), addi(R25, R25, 2),
 sfnei(R6, 0x24), bf('bl_loop'),
 jr(R9),
 # ---- vertical shift (r3 = buffer, r4 = rows): vendor body on the buffer and on its shadow
 'vshift2:',
 mov(R24, R4), mov(R26, R9),
 *SHADOW(R25, R3),
 jal('vbody'),
 mov(R3, R25), mov(R4, R24), jal('vbody'),
 jr(R26),
 # ---- merge (inline at 0x27C257, r22 = buffer A): B |= A for both planes, then the vendor flush call
 'merge2:',
 addi(R6, R1, 0x4C), mov(R5, R22),
 'mg_a:',
 lhz(R23, 0, R6), lhz(R4, 0, R5), orr(R7, R23, R4), sh(0, R6, R7),
 addi(R6, R6, 2), addi(R5, R5, 2), addi(R7, R1, 0x70), bne(R7, R6, 'mg_a'),
 *const32(R6, SH + 0x24), *const32(R5, SH), *const32(R24, SH + 0x48),
 'mg_b:',
 lhz(R23, 0, R6), lhz(R4, 0, R5), orr(R7, R23, R4), sh(0, R6, R7),
 addi(R6, R6, 2), addi(R5, R5, 2), bne(R24, R6, 'mg_b'),
 j(MERGE_CONT),
 # ---- flush (r3 = buffer B): one 2-bit glyph at the mapped code of the next logical code
 'flush2:',
 *SHADOW(R25, R3),
 *f_pro,
 mov(R10, R3), mov(R11, R25),
 *ram(R7), lbz(R12, lo(CUR_B), R7), slli(R12, R12, 8), lbz(R6, lo(CUR_S), R7), orr(R3, R12, R6),
 addi(R6, R6, 1), sb(lo(CUR_S), R7, R6),                  # slot is 8 bit, as the vendor counter
 jal('lmap'), beqi(R3, 0, 'fl_done'),
 muli(R13, R3, 12), addi(R13, R13, 0x880),                # RAM word of 2-bit code P
 *call(WMASK, ('c', MODE), ('c', 0), ('c', 0x1F)),
 *call(W16, ('c', PORT), ('r', R13)),
 *call(WMASK, ('c', MODE), ('c', 3), ('c', 0x1F)),
 ori(R12, R0, 18),
 'fl_row:',
 lhz(R3, 0, R10), lhz(R4, 0, R11),
 ('bt.movi', {'D': R14, 'I': 0}), ori(R5, R0, 11),
 'fl_px:',                                                # 24 bits: pixel value 2 x B + A, leftmost first
 slli(R14, R14, 2),
 srl(R6, R4, R5), andi(R6, R6, 1), slli(R6, R6, 1), orr(R14, R14, R6),
 srl(R6, R3, R5), andi(R6, R6, 1), orr(R14, R14, R6),
 addi(R5, R5, -1), bgtsi(R5, -1, 'fl_px'),
 srli(R4, R14, 16), extbz(R4, R4), *const32(R3, PORT), jal(RIU_WR),
 srli(R4, R14, 8), extbz(R4, R4), *const32(R3, PORT), jal(RIU_WR),
 extbz(R4, R14), *const32(R3, PORT), jal(RIU_WR),
 addi(R10, R10, 2), addi(R11, R11, 2), addi(R12, R12, -1), bnei(R12, 0, 'fl_row'),
 'fl_done:',
 *f_epi, jr(R9),
 # ---- logical code r3 -> 2-bit code r3 (0 = not text); r7 only
 'lmap:',
 ori(R7, R0, 0x20), bgtu(R7, R3, 'lm_no'),
 ori(R7, R0, 0x164), bgtu(R7, R3, 'lm_a'),
 ori(R7, R0, 0x195), bgtu(R7, R3, 'lm_b'),
 ori(R7, R0, 0x1C0), bgtu(R7, R3, 'lm_no'),
 ori(R7, R0, 0x1DA), bgtu(R7, R3, 'lm_c'),
 'lm_no:', ('bt.movi', {'D': R3, 'I': 0}), jr(R9),
 'lm_a:', add(R3, R3, R3), addi(R3, R3, 0x38), jr(R9),
 'lm_b:', add(R3, R3, R3), addi(R3, R3, 0x48), jr(R9),
 'lm_c:', add(R3, R3, R3), addi(R3, R3, 0x4A), jr(R9),
 # ---- text placement (from 0x25CB21: mode 2 and tile address r16 set; r13 = &count, r14 = &first,
 #      r15 bit 7 = attributes only). r10-r16 are saved by 0x25CA96.
 'place2:',
 mh(R7, 0x45), lbz(R12, 0x7889, R7), andi(R12, R12, 0xF), slli(R12, R12, 8),   # r12 = code bits 8-11, shifted
 mh(R7, 0x3C), lbz(R11, 0x5389, R7),                      # r11 = attribute
 lbz(R3, 0, R14), orr(R3, R3, R12), jal('lmap'), beqi(R3, 0, 'pl_attr'),
 mov(R3, R11), jal('gattr'), mov(R11, R3),                # text: attribute with its palette group
 'pl_attr:',
 *call(WMASK, ('c', MODE), ('c', 0), ('c', 0x1F)),
 *call(W16, ('c', PORT), ('r', R16)),
 *call(WMASK, ('c', MODE), ('c', 2), ('c', 0x1F)),
 ('bt.movi', {'D': R10, 'I': 0}),
 'pl_aloop:',
 *const32(R3, PORT), mov(R4, R11), jal(RIU_WR),
 addi(R10, R10, 1), lbz(R7, 0, R13), bgtu(R7, R10, 'pl_aloop'),
 extbs(R7, R15), blesi(R7, -1, 'pl_ret'),                 # attributes only
 addi(R1, R1, -4),                                        # 0(r1): code of the current tile
 ('bt.movi', {'D': R10, 'I': 0}), ori(R11, R0, 0xFFFF),   # r10 = tile, r11 = code bits 8-11 of the open run
 'pl_cloop:',
 lbz(R3, 0, R14), add(R3, R3, R10), andi(R3, R3, 0xFF), orr(R3, R3, R12), jal('lmap'),
 bnei(R3, 0, 'pl_have'),
 lbz(R3, 0, R14), add(R3, R3, R10), andi(R3, R3, 0xFF), orr(R3, R3, R12),   # not text: vendor code
 'pl_have:',
 sw(0, R1, R3),
 srli(R7, R3, 8), beq(R7, R11, 'pl_put'),
 mov(R11, R7),                                            # new run: mode 0, address, mode 1, code bits 8-11
 *call(WMASK, ('c', MODE), ('c', 0), ('c', 0x1F)),
 add(R4, R16, R10), *const32(R3, PORT), jal(W16),
 *call(WMASK, ('c', MODE), ('c', 1), ('c', 0x1F)),
 *const32(R3, CODEHI), mov(R4, R11), ori(R5, R0, 0xF), jal(WMASK),
 'pl_put:',
 lw(R4, 0, R1), extbz(R4, R4), *const32(R3, PORT), jal(RIU_WR),
 addi(R10, R10, 1), lbz(R7, 0, R13), bgtu(R7, R10, 'pl_cloop'),
 addi(R1, R1, 4),
 'pl_ret:',
 j(PLACE_RET),
 # ---- attribute r3 -> attribute with a text palette group (assigned on first use)
 'gattr:',
 *g_pro,
 mov(R10, R3), *const32(R7, TMAP), add(R7, R7, R10), lbz(R7, 0, R7),
 beqi(R7, 0, 'ga_new'),
 addi(R7, R7, -1), j('ga_ret'),
 'ga_new:',
 *ram(R7), lbz(R11, lo(NGRP), R7),
 ori(R6, R0, len(POOL)), bleu(R6, R11, 'ga_full'),
 *const32(R6, 0), 'ga_pool_ref:',                          # r6 = pool table (patched below)
 add(R6, R6, R11), lbz(R6, 0, R6),                         # r6 = group
 *ram(R7), addi(R5, R11, 1), sb(lo(NGRP), R7, R5),
 add(R5, R7, R11), sb(lo(GATTR), R5, R10),
 *const32(R7, TMAP), add(R7, R7, R10), addi(R5, R6, 1), sb(0, R7, R5),
 mov(R11, R6),
 mov(R3, R6), mov(R4, R10), jal('setgrp'),
 mov(R7, R11),
 'ga_ret:',
 slli(R7, R7, 4), andi(R3, R10, 0xF), orr(R3, R3, R7),
 *g_epi, jr(R9),
 'ga_full:',
 mov(R3, R10), *g_epi, jr(R9),                            # more than 12 text attributes: unchanged
 # ---- load group r3 with [bg, 1/3, 2/3, fg] of attribute r4 (1-bit palette entries from PAL16)
 'setgrp:',
 *s_pro,
 mov(R10, R3),
 srli(R7, R4, 4), andi(R7, R7, 0xF), muli(R7, R7, 3), *const32(R11, PAL16), add(R11, R11, R7),   # fg
 andi(R7, R4, 0xF), muli(R7, R7, 3), *const32(R12, PAL16), add(R12, R12, R7),                   # bg
 *const32(R5, PTAB), ('bt.movi', {'D': R6, 'I': 0}),
 'sg_ch:',
 add(R7, R11, R6), lbz(R3, 0, R7),                        # f
 add(R7, R12, R6), lbz(R4, 0, R7),                        # b
 add(R7, R5, R6), sb(0, R7, R4), sb(12, R7, R3),          # entries 0 (b) and 3 (f)
 add(R23, R4, R4), add(R23, R23, R3), muli(R23, R23, 0x5556), addi(R23, R23, 0x7FFF), srli(R23, R23, 16),
 sb(4, R7, R23),                                          # (2b + f) / 3
 add(R23, R3, R3), add(R23, R23, R4), muli(R23, R23, 0x5556), addi(R23, R23, 0x7FFF), srli(R23, R23, 16),
 sb(8, R7, R23),                                          # (b + 2f) / 3
 addi(R6, R6, 1), bnei(R6, 3, 'sg_ch'),
 ('bt.movi', {'D': R3, 'I': 0}), slli(R4, R10, 4), *const32(R5, PTAB), ('bt.movi', {'D': R6, 'I': 4}),
 jal('tramp'),
 *s_epi, jr(R9),
 # ---- palette loader hook (r3 = sel, r4 = first index, r5 = table, r6 = count)
 'palhook:',
 bnei(R3, 0, 'tramp'),
 *h_pro,
 addi(R1, R1, -16), sw(0, R1, R3), sw(4, R1, R4), sw(8, R1, R5), sw(12, R1, R6),
 ('bt.movi', {'D': R10, 'I': 0}),
 'ph_rec:',
 bleu(R6, R10, 'ph_load'),
 add(R7, R4, R10), ori(R11, R0, 15), bgtu(R7, R11, 'ph_next'),
 muli(R7, R7, 3), *const32(R11, PAL16), add(R11, R11, R7),
 slli(R12, R10, 2), add(R12, R12, R5),
 lbz(R7, 0, R12), sb(0, R11, R7), lbz(R7, 1, R12), sb(1, R11, R7), lbz(R7, 2, R12), sb(2, R11, R7),
 'ph_next:',
 addi(R10, R10, 1), j('ph_rec'),
 'ph_load:',
 lw(R3, 0, R1), lw(R4, 4, R1), lw(R5, 8, R1), lw(R6, 12, R1), addi(R1, R1, 16),
 jal('tramp'),
 ('bt.movi', {'D': R10, 'I': 0}),
 'ph_grp:',
 *ram(R7), lbz(R11, lo(NGRP), R7), bleu(R11, R10, 'ph_ret'),
 add(R7, R7, R10), lbz(R4, lo(GATTR), R7),
 *const32(R3, 0), 'ph_pool_ref:',
 add(R3, R3, R10), lbz(R3, 0, R3),
 jal('setgrp'),
 addi(R10, R10, 1), j('ph_grp'),
 'ph_ret:',
 *h_epi, jr(R9),
 # ---- vendor palette loader without the hook
 'tramp:',
 addi(R1, R1, -0x20), sw(0x1C, R1, R9), j(PAL_CONT),
 # ---- vendor vertical shift body (copied)
 'vbody:',
]

def build(pool_addr):
    p = []
    for k, x in enumerate(prog):
        if isinstance(x, str) and x.endswith('_ref:'):     # preceding const32(r, 0) -> pool address
            r = p[-2][1]['D']
            p[-2:] = const32(r, pool_addr)
        p.append(x)
    code, L = S.assemble(p, CODE)
    return code, L

code, L = build(0)
code = code + vbody
pool_addr = CODE + len(code)
code, L = build(pool_addr)
code = code + vbody
assert CODE + len(code) == pool_addr
code += bytes(POOL)
assert CODE + len(code) <= CODE_END, hex(CODE + len(code))
for a, b, x in A.disasm(code[:pool_addr - CODE - len(vbody)], CODE, pool_addr - len(vbody), CODE):
    lab = [k for k, v in L.items() if v == a and not k.endswith('_ref')]
    print(('%-11s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
print('vbody %#x, pool %#x, end %#x' % (L['vbody'], pool_addr, CODE + len(code)))

# ---------------------------------------------------------------- font data
FONT = os.environ.get('FONT', 'NotoSans-CondensedSemiBold.ttf')
SIZE, BASELINE = 14, 14              # px per em; first row below the baseline (vendor: caps on rows 4-13)
CHARS = {0x0F: ' ', 0x10: '.', 0x11: ',', 0x12: '?', 0x13: ':', 0x14: ';', 0x15: "'", 0x16: '"', 0x17: '/',
         0x18: '(', 0x19: ')', 0x0B: '@', 0x0C: '&', 0x0D: '+', 0x0E: '-', 0x54: '…',
         0x64: 'ñ', 0x65: 'ç', 0x70: 'é', 0x71: 'ó', 0x72: 'ö', 0x73: 'ä', 0x74: 'è', 0x75: 'á', 0x76: 'ü',
         0x77: 'É', 0x78: 'î', 0x79: 'ß', 0x7A: 'à', 0x7B: '°', 0x7C: 'ú', 0x7D: 'í'}
for i in range(10): CHARS[1 + i] = str(i)
for i in range(26): CHARS[0x20 + i] = chr(65 + i); CHARS[0x3A + i] = chr(97 + i)
assert max(CHARS) < PB_CODES
font = ImageFont.truetype(FONT, SIZE)

GAMMA = 0.75                         # coverage -> level curve (slightly bolder than linear, closest to the unquantised rendering)
FAINT = 153                          # column alpha sum below which an overhang column is dropped (0.6 px of ink)
def render(ch):
    """12 x 18 pixel values 0-3 and the glyph width (= rounded Noto advance; renderer letter spacing is 0)."""
    w = round(font.getlength(ch))
    im = Image.new('L', (32, 18), 0)
    ImageDraw.Draw(im).text((8, BASELINE), ch, font=font, anchor='ls', fill=255)
    px = im.load()
    weight = lambda x: sum(px[x, y] for y in range(18))
    def drop(x):
        for y in range(18):
            px[x, y] = 0
    cols = [x for x in range(32) if weight(x)]
    while cols and cols[0] < 8 and weight(cols[0]) < FAINT:        # faint ink left of the pen position
        drop(cols.pop(0))
    while cols and cols[-1] >= 8 + w and weight(cols[-1]) < FAINT:  # faint ink beyond the advance
        drop(cols.pop())
    while cols and cols[-1] - cols[0] >= 12:                        # wider than the 12 px box: drop the fainter edge
        drop(cols.pop(0) if weight(cols[0]) <= weight(cols[-1]) else cols.pop())
    shift = 0
    if cols:
        shift = max(0, 8 - cols[0])                 # remaining ink left of the pen position: move right
        w = max(w, cols[-1] - 8 + shift + 1)
    w = max(1, min(w, 12))
    full = Image.new('L', (32, 40), 0)              # clipping check: nothing above row 0 or below row 17
    ImageDraw.Draw(full).text((8, BASELINE + 11), ch, font=font, anchor='ls', fill=255)
    fp = full.load()
    assert not any(fp[x, y] for x in range(32) for y in list(range(11)) + list(range(29, 40))), 'clipped: %r' % ch
    v = [[int(3 * (px[x + 8 - shift, y] / 255) ** GAMMA + 0.5) if x + 8 - shift < 32 else 0 for x in range(12)] for y in range(18)]
    return w, v

def record(w, plane):                # vendor record: header (left blank << 4 | right blank), 0, 19 rows LE
    out = bytearray([12 - w, 0])
    for y in range(19):
        r = 0
        if y < 18:
            for x in range(12):
                if plane[y][x]:
                    r |= 0x800 >> x
        out += r.to_bytes(2, 'little')
    return bytes(out)

set0 = bytearray(cur(FONT_TAB, PB_CODES * 40))
set1 = bytearray(PB_CODES * 40)
glyphs = {}
for c in range(PB_CODES):
    if c in CHARS:
        w, v = render(CHARS[c])
        glyphs[c] = (w, v)
        set0[40 * c:40 * c + 40] = record(w, [[p & 1 for p in row] for row in v])
        set1[40 * c:40 * c + 40] = record(w, [[p >> 1 for p in row] for row in v])
    else:                            # vendor bitmap in both planes (full intensity), e.g. CJK language names
        set1[40 * c:40 * c + 40] = set0[40 * c:40 * c + 40]
set0, set1 = bytes(set0), bytes(set1)

# preview: all Latin glyphs, 4 grey levels
pv = Image.new('L', (len(glyphs) * 13, 18), 40)
for k, c in enumerate(sorted(glyphs)):
    w, v = glyphs[c]
    for y in range(18):
        for x in range(12):
            pv.putpixel((13 * k + x, y), (40, 105, 170, 235)[v[y][x]])
if os.environ.get('PREVIEW'):
    pv.resize((pv.width * 3, pv.height * 3), Image.NEAREST).save(os.environ['PREVIEW'])

# page budget check with these widths (vendor text blocks, see section 56)
def tiles(b):
    t = 0
    for s in b.split(b'\0'):
        if s:
            t += math.ceil(sum(glyphs[c][0] if c in glyphs else 12 for c in s if c < 0xF0) / 12)
    return t
worst = {}
for st in range(0x40):
    p = u32(0x326C98 + 4 * st)
    if not 0x300000 <= p < 0x3D0000:
        continue
    for lang in (0, 2, 3, 4):        # English, Spanish, German, French
        sp, n = u32(p + 8 * lang), u16(p + 8 * lang + 4)
        if 0x300000 <= sp < 0x3D0000 and n < 5000:
            worst[st] = max(worst.get(st, 0), tiles(cur(sp, n)))
common = max(tiles(cur(u32(0x3BFF18 + 8 * l), u16(0x3BFF18 + 8 * l + 4))) for l in (0, 2, 3, 4))
print('page blocks (tiles, max of EN/ES/DE/FR):', ' '.join('%02X:%d' % kv for kv in sorted(worst.items())))
print('common block: %d tiles' % common)
assert max(worst.values()) <= 0x100 - 0x20, 'page text exceeds codes 0x20-0xFF'
assert 0x20 + common <= 0x195 - 0x100, 'common block exceeds the mapped bank-1 range'

# ---------------------------------------------------------------- checks of the vendor code relied on
def insn(a): return A.decode(d, a - 0x200000, a)
assert cur(RENDER_START, 4) == S.encode('bg.jal', {'/': ADDR_SET}, RENDER_START)
assert insn(BLIT)['ops'] == 'r7,0xc' and insn(BLIT + 2)['ops'] == 'r7,r7,r6'
assert insn(CLEAR)['ops'] == 'r6,0x0' and insn(CLEAR + 2)['ops'] == 'r7,r3,r6'
assert insn(VSHIFT)['ops'] == 'r7,r4' and insn(VSHIFT_END - 2)['mnem'] == 'b.j'
assert insn(MERGE)['ops'] == 'r6,r1,0x4c' and insn(MERGE + 3)['ops'] == 'r5,r22'
assert insn(MERGE_CONT)['ops'] == 'r3,r1,0x4c' and insn(MERGE_CONT + 3)['target'] == FLUSH
assert insn(FLUSH)['ops'] == 'r1,r1,-0x10' and insn(FLUSH + 2)['ops'] == '0xc(r1),r9'
assert insn(PLACE)['ops'] == 'r6,0x1(r14)' and insn(PLACE_RET)['ops'] == 'r16,0x0(r1)'
assert insn(0x25CB4C)['ops'] == 'r7,r15' and insn(0x25CB93)['ops'] == 'r7,0x0(r13)'
assert insn(PAL)['ops'] == 'r1,r1,-0x20' and insn(PAL + 3)['ops'] == '0x1c(r1),r9' and insn(PAL_CONT)['ops'] == '0x18(r1),r10'
assert insn(RANGE_SET)['name'] == 'bg.ori' and insn(RANGE_SET)['ops'] == 'r4,r0,0x300' and insn(RANGE_SET + 4)['target'] == 0x23C24F
assert cur(HALF_LOAD, 3).hex() == '5060fe' and cur(HALF_PUT1, 3).hex() == '50a0fe' and cur(HALF_PUT2, 3).hex() == '50a0ff'
assert insn(HALF_LOAD + 13)['target'] == 0x27BC9C and insn(HALF_PUT1 + 3)['target'] == 0x25C70B
assert insn(0x259A3F)['ops'] == 'r7,r7,-0x4f98'         # font pointer 0x453DE8 = 0x3C0000 - 0x4F98 = 0x3BB068
for a in SPACING:                                        # listed from the renderer disassembly (lbz 0x3CB81C, andi 3)
    assert insn(a)['name'] == 'bn.andi' and insn(a)['ops'].endswith(',0x3'), hex(a)
assert cur(CODE, CODE_END - CODE) == b'\0' * (CODE_END - CODE)
assert cur(RAM, RAM_END - RAM) == b'\0' * (RAM_END - RAM)

# ---------------------------------------------------------------- edits
hook = lambda name, at, lab: {'addr': '0x%06X' % at, 'old': cur(at, 4).hex(),
                              'new': S.encode('bg.j', {'/': L[lab]}, at).hex(), 'asm': name}
edits = [
 {'addr': '0x%06X' % CODE, 'old': '00' * len(code), 'new': code.hex(),
  'asm': 'osd-aa code (image head zero area 0x203000): renderer helpers for 2-bit glyphs, code map, text placement, palette groups; RAM 0x202D00-0x202EAF'},
 {'addr': '0x%06X' % RENDER_START, 'old': cur(RENDER_START, 4).hex(),
  'new': S.encode('bg.jal', {'/': L['start2']}, RENDER_START).hex(), 'asm': 'renderer 0x27C046: jal 0x25D952 -> jal start2 (remember bank and first slot)'},
 hook('blit 0x27BF05 -> j blit2 (both glyph planes)', BLIT, 'blit2'),
 hook('tile clear 0x27BEF3 -> j clear2 (and its plane-B shadow)', CLEAR, 'clear2'),
 hook('vertical shift 0x27BE4D -> j vshift2 (vendor body on both planes)', VSHIFT, 'vshift2'),
 hook('renderer merge B |= A at 0x27C257 -> j merge2 (both planes)', MERGE, 'merge2'),
 hook('tile flush 0x27BFCF -> j flush2 (2-bit glyph at the mapped code)', FLUSH, 'flush2'),
 hook('text placement 0x25CA96 at 0x25CB21 -> j place2 (mapped codes, text palette groups)', PLACE, 'place2'),
 hook('palette loader 0x2533CE -> j palhook (record entries 0-15, reload text groups)', PAL, 'palhook'),
 {'addr': '0x%06X' % RANGE_SET, 'old': cur(RANGE_SET, 4).hex(),
  'new': S.encode('bg.ori', {'D': R4, 'A': R0, 't': TWO_BIT_START}, RANGE_SET).hex(),
  'asm': 'sub_253991: 2-bit code range start 0x101C0A 0x300 -> 0x%03X' % TWO_BIT_START},
 {'addr': '0x%06X' % HALF_LOAD, 'old': cur(HALF_LOAD, 3).hex(),
  'new': S.encode('bn.ori', {'D': R3, 'A': R0, 'N': HALF_CODE}, HALF_LOAD).hex(),
  'asm': 'sub_253991: half-circle glyphs (set 0x325C80) loaded to 0x%02X/0x%02X instead of 0xFE/0xFF' % (HALF_CODE, HALF_CODE + 1)},
 {'addr': '0x%06X' % HALF_PUT1, 'old': cur(HALF_PUT1, 3).hex(),
  'new': S.encode('bn.ori', {'D': R5, 'A': R0, 'N': HALF_CODE}, HALF_PUT1).hex(), 'asm': 'sub_254ED0: left half circle code 0xFE -> 0x%02X' % HALF_CODE},
 {'addr': '0x%06X' % HALF_PUT2, 'old': cur(HALF_PUT2, 3).hex(),
  'new': S.encode('bn.ori', {'D': R5, 'A': R0, 'N': HALF_CODE + 1}, HALF_PUT2).hex(), 'asm': 'sub_254ED0: right half circle code 0xFF -> 0x%02X' % (HALF_CODE + 1)},
 *[{'addr': '0x%06X' % a, 'old': cur(a, 3).hex(), 'new': cur(a, 2).hex() + '00',
    'asm': 'renderer letter spacing (0x3CB81C & 3) -> 0: the Noto glyph widths include the side bearings'} for a in SPACING],
 {'addr': '0x%06X' % FONT_TAB, 'old': cur(FONT_TAB, len(set0)).hex(), 'new': set0.hex(),
  'asm': 'font set 0 codes 0x00-0x7D: Noto Sans Condensed SemiBold 14 px, pixel bit 0 (Latin codes; others unchanged)'},
 {'addr': '0x%06X' % (FONT_TAB + PB_OFF), 'old': cur(FONT_TAB + PB_OFF, len(set1)).hex(), 'new': set1.hex(),
  'asm': 'font set 1 codes 0x00-0x7D (vendor CJK): pixel bit 1 of set-0 codes 0x00-0x7D'},
]
for e in edits:
    assert len(e['old']) == len(e['new']), e['asm']
patch = {
 'name': 'osd-aa-font',
 'summary': 'Anti-aliased OSD text: Noto Sans Condensed SemiBold 14 px rendered as 2-bit (4-level) glyphs, smooth edges in every text colour',
 'status': 'experimental, hardware test pending (prototype v1)',
 'edits': edits,
 'labels': {k: '0x%06X' % v for k, v in L.items() if not k.endswith('_ref')},
 'notes': ("Text tiles become 2-bit glyphs (two code slots each). Logical codes L = bank << 8 | slot map to 2-bit codes: "
           "0x020-0x163 -> 2L+0x38, 0x164-0x194 -> 2L+0x48, 0x1C0-0x1D9 -> 2L+0x4A; vendor icons stay at 0x300-0x30F and "
           "0x372-0x3C9; 2-bit range from 0x078 (0x101C0A). Each text attribute gets a free palette group (6, 7, 8, 9, B-F, "
           "3-5) with [background, 1/3, 2/3, foreground] of its 1-bit colours, reloaded after every palette load. "
           "Chinese and Japanese are not supported (their glyph set holds the second bit plane). "
           "Font: Noto Sans Condensed SemiBold (SIL Open Font License 1.1, docs/licenses/NotoSans-OFL.txt). "
           "Generated by tools/patches_src_osd_aa.py."),
}
out = os.environ.get('OUT', 'osd-aa-font.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
print('wrote', out)
