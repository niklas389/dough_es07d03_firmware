#!/usr/bin/env python3
"""osdtest.py - OSD font/tile experiments over DDC (needs diag-poke + diag-fe + diag-osd).

    tools/osdtest.py info  > osd_info.txt       dump the OSD registers (0x101C00-1F, 0x101C60-7F, 0x101D00-FF)
    tools/osdtest.py glyphs                     load the 2-bit (4-colour) test glyphs (codes 0x3B0-0x3B3, 0x3CF)
    tools/osdtest.py row 11                     show them in row 11 of window 1 (menu open), from column 1
    tools/osdtest.py row 11 --col 3 --win 1
    tools/osdtest.py place 1 5 11 0x3B0 0x21    one tile: window, column, row, code, attribute
    SPECCTL=./specctl MON=1 TRIES=10 tools/osdtest.py ...

Test glyphs (docs/firmware-map.md section 56):
  0x3B0  four vertical bands, 3 px each, pixel values 0, 1, 2, 3 (left to right)
  0x3B1-0x3B3  an anti-aliased "Abg" sample over three tiles (values 0-3)
  0x3CF  the band glyph again in the last 2-bit code that fits the OSD RAM
'row' places: the solid base glyph 6 as a position marker, 0x3B0 eight times with the
attributes 21 12 2F F2 40 04 84 C8 (high nibble = foreground, low nibble = background in
1-bit tiles), a gap, the sample with attribute 21, a gap, 0x3CF with attribute 21, a marker.

OSD RAM (hardware test 2026-10-09, section 56): one address space of 0x4000 words for tiles
and glyphs; tiles at the bottom (tile address = word), glyphs from word 0x880 (0x101C08 x 4);
a 1-bit glyph takes 12 words, a 2-bit glyph 24 (18-bit words). With the stock ranges the 2-bit
codes start at word 0x2C80, so only 0x300-0x3CF fit; v1 of this tool used 0x3F0-0x3FE, whose
addresses wrapped to word 0x300 and overwrote menu tiles (row 12) instead.

Everything written is OSD display state only: closing and reopening the menu redraws the
tiles; the font RAM keeps the test glyphs until the next power cycle (codes 0x3B0-0x3CF are
not used by the firmware's text). The firmware's own OSD activity can interleave with these
writes; then just run the command again.
"""
import argparse, os, re, subprocess, sys, time

SPECCTL = os.environ.get('SPECCTL', 'specctl')
MON = os.environ.get('MON', '0')
TRIES = int(os.environ.get('TRIES', '4'))

def vset(code, val):
    subprocess.run([SPECCTL, 'set', '0x%02X' % code, str(val), '-d', MON, '--fast'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def vget(code):
    r = subprocess.run([SPECCTL, 'get', '0x%02X' % code, '-d', MON, '--fast'],
                       capture_output=True, text=True)
    m = re.search(r'= (\d+) ', r.stdout)
    return int(m.group(1)) if m else None

_hi = None
def setaddr(a):
    """diag-poke address variable (VCP 0xEA/0xEB), verified."""
    global _hi
    hi, lo = (a >> 16) & 0xFFFF, a & 0xFFFF
    for _ in range(TRIES):
        if _hi != hi:
            vset(0xEA, hi)
        vset(0xEB, lo)
        if (_hi == hi or vget(0xEA) == hi) and vget(0xEB) == lo:
            _hi = hi
            return
        _hi = None
        time.sleep(0.3)
    sys.exit('address %#x not accepted (diag-poke in the build? DDC/CI working?)' % a)

def rd(a):
    """one OSD register (VCP 0xEE) or, for 0x20xxxx, a RAM byte through diag-poke (VCP 0xEC)."""
    setaddr(a)
    code = 0xEC if (a >> 16) == 0x20 else 0xEE
    for _ in range(TRIES):
        v = vget(code)
        if v is not None:
            if v > 0xFF:
                sys.exit('read of %#x blocked (diag-osd in the build?)' % a)
            return v
    sys.exit('read of %#x failed' % a)

def wr(a, v):
    setaddr(a)
    vset(0xEE, v & 0xFF)

def counter():
    return rd(0x2024B0)

def checked(fn, n, what):
    """run fn() (n accepted writes expected); retry when DDC/CI dropped one."""
    for t in range(TRIES):
        c0 = counter()
        fn()
        c1 = counter()
        if (c1 - c0) & 0xFF == n:
            return
        print('  %s: %d of %d writes arrived, again' % (what, (c1 - c0) & 0xFF, n), file=sys.stderr)
    sys.exit('%s: DDC/CI kept dropping writes' % what)

# ---- glyph data: 18 rows x 12 pixel values 0-3 -> 3 bytes per row (pixel 0 in bits 23-22) ----
def pack(rows):
    out = bytearray()
    for r in rows:
        v = 0
        for ch in r:
            v = (v << 2) | int(ch)
        out += bytes([v >> 16, (v >> 8) & 0xFF, v & 0xFF])
    assert len(out) == 54
    return bytes(out)

BANDS = ['000111222333'] * 18
SAMPLE = ['000000000000000000000000000000000000', '000000000000000000000000000000000000',
          '000000000000000000000000000000000000', '000003300000220000000000000000000000',
          '000013320000220000000000000000000000', '000022230000220000000000000000000000',
          '000031031000222332100002332130000000', '000130022000232002300013101330000000',
          '000220013000230000310031000130000000', '001310003100220000220031000130000000',
          '002333333200220000220031000130000000', '003200001310230000310031000130000000',
          '013100000320232002300013101330000000', '023000000230222332100002332130000000',
          '000000000000000000000000000130000000', '000000000000000000000012001320000000',
          '000000000000000000000001333100000000', '000000000000000000000000000000000000']
GLYPHS = {0x3B0: pack(BANDS), 0x3CF: pack(BANDS)}
for k in range(3):
    GLYPHS[0x3B1 + k] = pack([r[12 * k:12 * k + 12] for r in SAMPLE])

BASE_UNIT, MONO_UNITS, FOUR_START = 0x220, 3, 0x300     # 0x101C08, 0x101C0B bits 4-5 + 1, 0x101C0A

def font_addr(code):
    """font RAM address (value for 0x101C66/67) of a 2-bit code; inferred from the firmware's two loads."""
    a = (BASE_UNIT + MONO_UNITS * FOUR_START + 2 * MONO_UNITS * (code - FOUR_START)) * 4
    assert FOUR_START <= code and a + 24 <= 0x4000, 'code %#x does not fit the OSD RAM' % code
    return a

def load_glyph(code, data):
    m68, m6d = rd(0x101C68), rd(0x101C6D)
    a = font_addr(code)
    def go():
        wr(0x101C6D, m6d & 0x3F)                       # as both firmware loaders
        wr(0x101C68, m68 & 0xE0)                       # mode 0: address
        wr(0x101C66, a & 0xFC)
        wr(0x101C67, a >> 8)
        wr(0x101C68, (m68 & 0xE0) | 3)                 # mode 3: font data
        setaddr(0x101C66)
        for b in data:
            vset(0xEE, b)
        wr(0x101C68, m68)
        wr(0x101C6D, m6d)
    checked(go, 7 + len(data), 'glyph %#x' % code)
    print('glyph %#05x loaded at font address %#06x' % (code, a))

def window(w):
    b = 0x101D00 + 0x20 * w
    return rd(b + 0x10) | rd(b + 0x11) << 8, rd(b + 0x12)

def place(w, col, row, code, attr, geo=None):
    base, pitch = geo or window(w)
    t = (base + row * pitch + col) & 0xFFFF
    m68 = rd(0x101C68)
    def go():
        wr(0x101C68, m68 & 0xE0)                       # mode 0: tile address
        wr(0x101C66, t & 0xFF)
        wr(0x101C67, t >> 8)
        wr(0x101C68, (m68 & 0xE0) | 2)                 # mode 2: attribute
        wr(0x101C66, attr)
        wr(0x101C68, m68 & 0xE0)
        wr(0x101C66, t & 0xFF)
        wr(0x101C67, t >> 8)
        wr(0x101C68, (m68 & 0xE0) | 1)                 # mode 1: code (bits 8-11 in 0x101C67 low nibble)
        hi = rd(0x101C67)
        wr(0x101C67, (hi & 0xF0) | (code >> 8))
        wr(0x101C66, code & 0xFF)
        wr(0x101C68, m68)
    checked(go, 12, 'tile %d/%d' % (col, row))
    print('window %d col %d row %d: code %#05x attribute %02X (tile address %#06x)' % (w, col, row, code, attr, t))

ap = argparse.ArgumentParser(description='OSD font/tile experiments (diag-osd)')
sub = ap.add_subparsers(dest='cmd', required=True)
sub.add_parser('info')
sub.add_parser('glyphs')
p = sub.add_parser('row'); p.add_argument('row', type=int)
p.add_argument('--col', type=int, default=1); p.add_argument('--win', type=int, default=1)
p = sub.add_parser('place')
for n in ('win', 'col', 'row', 'code', 'attr'):
    p.add_argument(n, type=lambda s: int(s, 0))
a = ap.parse_args()

if a.cmd == 'info':
    print('# osdtest info %s' % time.strftime('%F %T'))
    for lo, hi in ((0x101C00, 0x101C20), (0x101C60, 0x101C80), (0x101D00, 0x101E00)):
        for x in range(lo, hi):
            if x == 0x101C66:
                print('0x%06X PORT' % x)
                continue
            print('0x%06X 0x%02X' % (x, rd(x)), flush=True)
elif a.cmd == 'glyphs':
    for code in sorted(GLYPHS):
        load_glyph(code, GLYPHS[code])
elif a.cmd == 'row':
    geo = window(a.win)
    print('window %d: tile base %#06x, pitch %d' % (a.win, geo[0], geo[1]))
    c = a.col
    place(a.win, c, a.row, 6, 0x21, geo); c += 1          # marker: solid base glyph 6
    for attr in (0x21, 0x12, 0x2F, 0xF2, 0x40, 0x04, 0x84, 0xC8):
        place(a.win, c, a.row, 0x3B0, attr, geo); c += 1
    c += 1
    for k in range(3):
        place(a.win, c, a.row, 0x3B1 + k, 0x21, geo); c += 1
    c += 1
    place(a.win, c, a.row, 0x3CF, 0x21, geo); c += 1
    place(a.win, c, a.row, 6, 0x21, geo)
else:
    place(a.win, a.col, a.row, a.code, a.attr)
