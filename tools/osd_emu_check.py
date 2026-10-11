#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Emulator checks for the anti-aliased OSD font (patches/osd-aa-font.json), no hardware needed.

  RT=runtime_0x200000.bin python3 tools/osd_emu_check.py [PATCH ...] [--png page.png]

PATCH: patch names from patches/ applied before osd-aa-font (e.g. popup-flat popup-round).
Runs the vendor code of the patched runtime image in tools/aeon/aeonemu.py:
- the OSD init loader 0x253991 (palette, base glyphs, half circles, common text block,
  icons, code ranges), once without and once with osd-aa-font: all 1-bit glyphs below
  the 2-bit range and the 2-bit icons must be identical (half circles: 0xFE/0xFF -> 0x20/0x21);
- the page text renderer 0x259A0E for the largest pages in English, Spanish, German and
  French: every rendered tile must equal the glyphs of the patched font table laid out
  with their widths (each string starts on a new tile), and the page must end at slot 0xFF
  or below;
- text placement 0x25CA96: codes, attributes (palette groups), attribute-only updates,
  non-text descriptors, and the group colours after a palette reload;
- the page drawing 0x256C92 of the menu pages 0x10-0x17 (English): every text descriptor
  placed (string descriptor tables 0x3C3EE8) must start on a string of the new layout;
  every 2-bit tile has an attribute with bits 1-0 = 0 (on the monitor bit 0 made pixel
  value 0 transparent); the selection bar interior has its text tiles at 0x60 and its
  blank 1-bit tiles at 0x61.
Exit status 1 on any failure.
"""
import json, math, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'aeon'))
from aeonemu import CPU

args = [a for a in sys.argv[1:]]
png = None
if '--png' in args:
    png = args[args.index('--png') + 1]
    del args[args.index('--png'):args.index('--png') + 2]
stock = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
u32 = lambda a: struct.unpack_from('<I', stock, a - 0x200000)[0]
u16 = lambda a: struct.unpack_from('<H', stock, a - 0x200000)[0]
fails = []

def image(names):
    img = bytearray(stock)
    for nm in names:
        for e in json.load(open(os.path.join(HERE, '..', 'patches', nm + '.json')))['edits']:
            if e.get('space') == 'pm51' or int(e['addr'], 16) < 0x200000:
                continue
            a, old, new = int(e['addr'], 16) - 0x200000, bytes.fromhex(e['old']), bytes.fromhex(e['new'])
            assert img[a:a + len(old)] == old, (nm, e['addr'])
            img[a:a + len(new)] = new
    return img

def boot(img):
    c = CPU(bytes(img))
    c.osd.regs.update({0x101D30: 1, 0x101D31: 0, 0x101D32: 62})   # window 1: tile base 1, pitch 62
    c.osd.regs[0x101C0B] = 0x20                                    # 1-bit glyph = 3 units (as set at boot)
    c.sh(0x45788A, 0x220)                                          # font RAM base (sub_2592D6)
    c.sb(0x3C538A, 1)
    c.call(0x253991)
    return c

def check(cond, msg):
    print(('ok    ' if cond else 'FAIL  ') + msg)
    if not cond:
        fails.append(msg)

ref = boot(image(args))
img = image(args + ['osd-aa-font'])
c = boot(img)
o = c.osd
rng = o.regs.get(0x101C0A, 0) | o.regs.get(0x101C0B, 0) << 8
check(rng & 0x3FF == 0x78, '2-bit range start 0x101C0A = %#x' % rng)
same = all(o.glyph(k, 1) == ref.osd.glyph(k, 1) for k in range(0x78) if k not in (0x20, 0x21))
check(same, '1-bit glyphs 0x00-0x77 (without 0x20/0x21) identical to the build without osd-aa-font')
check(o.glyph(0x20, 1) == ref.osd.glyph(0xFE, 1) and o.glyph(0x21, 1) == ref.osd.glyph(0xFF, 1),
      'half circles at 0x20/0x21 (vendor: 0xFE/0xFF)')
icons = list(range(0x372, 0x3CA, 2))
check(all(o.glyph(k, 2) == ref.osd.glyph(k, 2) for k in icons), '2-bit icons 0x372-0x3C9 unchanged')
run = o.glyph(0x302, 2)                                  # selection bar: top run piece (v5)
check(all(v in (0, 1, 2, 3) for k in range(0x300, 0x310, 2) for row in o.glyph(k, 2) for v in row)
      and all(set(run[y]) == {2} for y in range(9)) and all(set(run[y]) == {0} for y in range(9, 12))
      and set(run[12]) == {1} and all(set(run[y]) == {3} for y in range(13, 18)),
      'selection bar pieces 0x300-0x30E: top run rows 0-8 value 2 (header band), 9-11 gap, edge at row 12, inside below')
stock_pal = stock[0x3B74B8 - 0x200000:0x3B74B8 - 0x200000 + 4 * 0xF8]
used = sorted({a & 0xFC for a in (0x10, 0x11, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 0x2C, 0xA8, 0xAC, 0xEC, 0xF1, 0xF4)})
check(not any(0x40 <= b < 0x70 or b == 0x78 for b in used),
      'text and bar palettes 0x40-0x6F, 0x78 clear of the vendor 2-bit attributes %s' % ' '.join('%02X' % b for b in used))

# patched font table (set 0 = bit 0, set 1 = bit 1 for codes below 0x7E)
F0 = bytes(img[0x3BB068 - 0x200000:0x3BB068 - 0x200000 + 0x7E * 40])
F1 = bytes(img[0x3BD868 - 0x200000:0x3BD868 - 0x200000 + 0x7E * 40])
def fglyph(cd):
    h = F0[40 * cd]
    rows = []
    for y in range(18):
        a, b = struct.unpack_from('<H', F0, 40 * cd + 2 + 2 * y)[0], struct.unpack_from('<H', F1, 40 * cd + 2 + 2 * y)[0]
        rows.append([((a >> (11 - x)) & 1) | (((b >> (11 - x)) & 1) << 1) for x in range(12)])
    return 12 - (h & 15) - (h >> 4), rows
lmap = lambda L: 2 * L + (0x66 if L < 0x1C else 0x5E if L < 0x151 else 0x6E if L < 0x182 else 0x4A)

last = None
for lang in (0, 2, 3, 4):
    c.sb(u32(0x3B5F38) + 0x78, lang)                       # settings: language
    for st in (0x08, 0x11, 0x13, 0x14, 0x15, 0x16, 0x17, 0x19):
        blk = u32(0x326C98 + 4 * st)
        sp, n = u32(blk + 8 * lang), u16(blk + 8 * lang + 4)
        c.sb(0x457854, st); c.sb(0x457888, 0)
        c.call(0x259A0E)
        tile = bad = 0
        for s in stock[sp - 0x200000:sp - 0x200000 + n].split(b'\0'):
            if not s:
                continue
            gl = [fglyph(cd) for cd in s]
            nt = math.ceil(sum(w for w, _ in gl) / 12)
            canvas = [[0] * (12 * nt) for _ in range(18)]
            x0 = 0
            for w, rows in gl:
                for y in range(18):
                    for x in range(w):
                        canvas[y][x0 + x] |= rows[y][x]
                x0 += w
            for t in range(nt):
                bad += o.glyph(lmap(0x20 + tile + t), 2) != [r[12 * t:12 * t + 12] for r in canvas]
            tile += nt
        check(bad == 0 and 0x20 + tile <= 0x100, 'lang %d page %02X: %3d tiles (slots 0x20-%#04x), %d tiles differ'
              % (lang, st, tile, 0x1F + tile, bad))
        last = (st, tile)

# placement: descriptor (first 0x20, 12 tiles) at column 2, row 3
D = 0x4F8000
c.sb(D, 0x20); c.sb(D + 1, 12); c.sb(0x457889, 0)
base = 1 + 3 * 62 + 2
c.sb(0x3C5389, 0x3F); c.call(0x25CA96, 2, 3, D)
codes = [o.code.get(base + i) for i in range(12)]
check(codes == [lmap(0x20 + i) for i in range(12)], 'text tiles get 2-bit codes 0x09E, 0x0A0, ...')
a1 = o.attr.get(base)
check(a1 is not None and 0x40 <= a1 < 0x70, 'attribute 0x3F -> %#04x (own 4-entry palette)' % (a1 or 0))
c.sb(0x3C5389, 0x2F); c.call(0x25CA96, 2, 3 | 0x80, D)
a2 = o.attr.get(base)
check(a2 not in (None, a1) and 0x40 <= a2 < 0x70 and all(o.attr.get(base + i) == a2 for i in range(12))
      and [o.code.get(base + i) for i in range(12)] == codes, 'attribute-only update 0x2F -> %#04x, codes kept' % (a2 or 0))
pal = lambda i: o.pal[i][::-1]                             # table byte order
g1 = [pal((a1 & 0xFC) + k) for k in range(4)]
check(g1[0] == pal(0xF) and g1[3] == pal(3) and g1[0] < g1[1] < g1[2] < g1[3],
      'palette of 0x3F = [bg 15, 1/3, 2/3, fg 3]: %s' % ' '.join(bytes(e).hex() for e in g1))
c.sb(D + 2, 1); c.sb(D + 3, 4); c.sb(0x3C5389, 0x21)
c.call(0x25CA96, 2, 5, D + 2)
b2 = 1 + 5 * 62 + 2
check([o.code.get(b2 + i) for i in range(4)] == [1, 2, 3, 4] and o.attr.get(b2) == 0x21, 'non-text descriptor unchanged')
c.call(0x25354E)                                           # vendor palette reload
check([pal((a1 & 0xFC) + k) for k in range(4)] == g1, 'text palette restored after a palette reload')

# full page drawing 0x256C92 (English): every text descriptor placed must be a string of the page's
# block as laid out with the new widths (first slot = string start, count = its tiles)
def new_starts(q, lang):
    sp, n = u32(q + 8 * lang), u16(q + 8 * lang + 4)
    b, out, slot, cur_s, i = stock[sp - 0x200000:sp - 0x200000 + n], set(), 0x20, bytearray(), 0
    def close(sx, slot):
        w = sum(fglyph(cd)[0] if cd < 0x7E else 12 for cd in sx if cd < 0xF0)
        t = math.ceil(w / 12)
        if t:
            out.add((slot, t))
        return slot + t
    while i < len(b):
        if b[i] == 0xFF:
            i += 2; continue
        if b[i] == 0:
            slot = close(cur_s, slot); cur_s = bytearray()
        else:
            cur_s.append(b[i])
        i += 1
    close(cur_s, slot)
    return out
c.sb(u32(0x3B5F38) + 0x78, 0)
for st in range(0x10, 0x18):
    seen = []
    def rec(cpu):
        seen.append((cpu.lb(0x457889) & 15, cpu.lb(cpu.r[14]), cpu.lb(cpu.r[14] + 1)))
        del cpu.stubs[0x25CB21]; cpu.step(); cpu.stubs[0x25CB21] = rec
    c.stubs[0x2714B4] = lambda cpu: setattr(cpu, 'pc', cpu.r[9])   # RTOS message (its pointer is set at boot)
    c.call(0x253991)
    c.sb(0x457854, 0x0E); c.call(0x256C92, 0)                      # menu frame: left list, information line
    c.stubs[0x25CB21] = rec
    c.sb(0x457854, st); c.call(0x256C92, 0)
    del c.stubs[0x25CB21]
    textattrs = {g - 1 for g in c.mem[0x202D80 - 0x200000:0x202E80 - 0x200000] if g}
    icon_codes = set(range(0x300, 0x310)) | set(range(0x372, 0x3CA))
    bar = lambda code, attr: 0x300 <= code < 0x310 and attr in (0x78, 0x6C)   # selection bar pieces (v5)
    clash = [a for a, code in o.code.items() if o.attr.get(a, 0) in textattrs and code in icon_codes
             and not bar(code, o.attr.get(a, 0))]
    check(not clash, 'page %02X with frame: no text tile on an icon code%s' % (st, '' if not clash else ' -- %d tiles' % len(clash)))
    # on the monitor a 2-bit tile whose attribute has bit 0 set showed pixel value 0 transparent (v4 photo)
    odd = [a for a, code in o.code.items() if code >= 0x78 and o.attr.get(a, 0) & 3]
    check(not odd, 'page %02X: every 2-bit tile has an attribute with bits 1-0 = 0%s' % (st, '' if not odd else ' -- %d tiles' % len(odd)))
    lefts = [a for a, code in o.code.items() if code == 0x30C]
    inner = []
    for a in lefts:
        b = a + 1
        while o.code.get(b) != 0x30E and b < a + 62:
            inner.append((o.code.get(b, 0), o.attr.get(b))); b += 1
    text = [at for cd, at in inner if cd >= 0x78]
    check(lefts and text and all(at == (0x60 if cd >= 0x78 else 0x61) for cd, at in inner),
          'page %02X: selection bar interior: %d text tiles attribute 0x60, %d blank tiles 0x61'
          % (st, len(text), len(inner) - len(text)))
    page = new_starts(u32(0x326C98 + 4 * st), 0)
    common = new_starts(0x3BFF18, 0)
    text = [x for x in seen if (x[0] << 8 | x[1]) >= 0x20 and x[0] < 2]   # (number fields: runtime descriptors)
    bad = [x for x in text if (x[1], x[2]) not in (page if x[0] == 0 else common)]
    check(text and not bad, 'page %02X drawn: %d text placements, all on string boundaries%s'
          % (st, len(text), '' if not bad else ' -- off: %s' % bad[:4]))

if png:
    from PIL import Image
    st, n = last
    sh = [(12, 12, 12), (88, 88, 90), (164, 162, 166), (240, 240, 245)]
    cols = 31
    im = Image.new('RGB', (cols * 12, math.ceil(n / cols) * 18), sh[0])
    for k in range(n):
        g = o.glyph(lmap(0x20 + k), 2)
        for y in range(18):
            for x in range(12):
                im.putpixel(((k % cols) * 12 + x, (k // cols) * 18 + y), sh[g[y][x]])
    im.resize((im.width * 3, im.height * 3), Image.NEAREST).save(png)
    print('wrote', png)
print('%d checks failed' % len(fails) if fails else 'all checks passed')
sys.exit(1 if fails else 0)
