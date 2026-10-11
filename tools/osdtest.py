#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""osdtest.py - OSD font/tile experiments over DDC (needs diag-poke + diag-fe + diag-osd).

Firmware-side test (diag-osd v3; seconds instead of a slow DDC upload):
    tools/osdtest.py load                       the firmware loads its built-in 2-bit test glyphs
    tools/osdtest.py row 11                     the firmware places the test row in row 11 (menu open)

    test glyphs (diag-osd v4; a 2-bit glyph uses two code slots): 0x3D0 bands (pixel values
    0,1,2,3 in 3-px bands), 0x3D2/0x3D4/0x3D6 solid value 1/2/3, 0x3D8/0x3DA/0x3DC anti-aliased
    "Abg" sample, 0x3DE bands
    test row, columns 1-28: marker (glyph 6, attribute 21); then for each attribute 21, F2, 40,
    C8, 12: bands, solid 1, solid 2, solid 3; blank; sample (3 tiles); blank; 0x3DE; marker.

Older DDC-side commands (diag-osd v2; every write checked, but about 1 s per byte; their glyph
address formula below is the disproved one, see section 56):

    tools/osdtest.py info  > osd_info.txt       dump the OSD registers (0x101C00-1F, 0x101C60-7F, 0x101D00-FF)
    tools/osdtest.py glyphs                     load the 2-bit (4-colour) test glyphs (codes 0x3B0-0x3B3, 0x3CF)
    tools/osdtest.py ddcrow 11                  show them in row 11 of window 1 (menu open), from column 1
    tools/osdtest.py ddcrow 11 --col 3 --win 1
    tools/osdtest.py place 1 5 11 0x3B0 0x21    one tile: window, column, row, code, attribute
    SPECCTL=./specctl MON=1 TRIES=10 tools/osdtest.py ...

Test glyphs (docs/firmware-map.md section 56):
  0x3B0  four vertical bands, 3 px each, pixel values 0, 1, 2, 3 (left to right)
  0x3B1-0x3B3  an anti-aliased "Abg" sample over three tiles (values 0-3)
  0x3CF  the band glyph again in the last 2-bit code that fits the OSD RAM
'ddcrow' places: the solid base glyph 6 as a position marker, 0x3B0 eight times with the
attributes 21 12 2F F2 40 04 84 C8 (high nibble = foreground, low nibble = background in
1-bit tiles), a gap, the sample with attribute 21, a gap, 0x3CF with attribute 21, a marker.

OSD RAM (hardware test 2026-10-09, section 56): one address space of 0x4000 words for tiles
and glyphs; tiles at the bottom (tile address = word), glyphs from word 0x880 (0x101C08 x 4);
a 1-bit glyph takes 12 words, a 2-bit glyph 24 (18-bit words). With the stock ranges the 2-bit
codes start at word 0x2C80, so only 0x300-0x3CF fit; v1 of this tool used 0x3F0-0x3FE, whose
addresses wrapped to word 0x300 and overwrote menu tiles (row 12) instead.

Every write is checked against diag-osd's write counter (RAM 0x2024B0) and resent if
DDC/CI dropped it (v1 of this tool lost about one write in ten). Load the glyphs first (the
menu may be closed; the font RAM keeps them), then open the menu and run 'row' (about 45
writes, well inside the 120 s menu timeout).

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
    for _ in range(max(10, 3 * TRIES)):                # hundreds of address changes per run
        if _hi != hi:
            vset(0xEA, hi)
        vset(0xEB, lo)
        if (_hi == hi or vget(0xEA) == hi) and vget(0xEB) == lo:
            _hi = hi
            return
        _hi = None
        time.sleep(0.1)
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

_cnt = None
def wr(a, v):
    """one verified write: diag-osd counts accepted writes at RAM 0x2024B0; a write that DDC/CI
    dropped (counter unchanged) is sent again. Data-port writes advance the RAM pointer only
    when they arrive, so resending keeps glyph and tile data in step."""
    global _cnt
    if _cnt is None:
        _cnt = rd(0x2024B0)
    for _ in range(3 * TRIES):
        setaddr(a)
        vset(0xEE, v & 0xFF)
        c = rd(0x2024B0)
        d, _cnt = (c - _cnt) & 0xFF, c
        if d == 1:
            return
        if d != 0:
            sys.exit('write counter jumped by %d at %#x (another DDC/CI writer?)' % (d, a))
    sys.exit('write %#x = %#x kept getting lost on DDC/CI' % (a, v))

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
    wr(0x101C6D, m6d & 0x3F)                           # as both firmware loaders
    wr(0x101C68, m68 & 0xE0)                           # mode 0: address
    wr(0x101C66, a & 0xFC)
    wr(0x101C67, a >> 8)
    wr(0x101C68, (m68 & 0xE0) | 3)                     # mode 3: font data
    for b in data:
        wr(0x101C66, b)
    wr(0x101C68, m68)
    wr(0x101C6D, m6d)
    print('glyph %#05x loaded at font address %#06x' % (code, a), flush=True)

def window(w):
    b = 0x101D00 + 0x20 * w
    return rd(b + 0x10) | rd(b + 0x11) << 8, rd(b + 0x12)

def run(w, col, row, tiles, geo=None):
    """consecutive tiles [(code, attr), ...] from (col, row): attributes in one burst (mode 2),
    then codes (mode 1), as sub_23C635 does for a row."""
    base, pitch = geo or window(w)
    t = (base + row * pitch + col) & 0xFFFF
    m68 = rd(0x101C68)
    wr(0x101C68, m68 & 0xE0)                           # mode 0: tile address
    wr(0x101C66, t & 0xFF)
    wr(0x101C67, t >> 8)
    wr(0x101C68, (m68 & 0xE0) | 2)                     # mode 2: attributes
    for code, attr in tiles:
        wr(0x101C66, attr)
    wr(0x101C68, m68 & 0xE0)
    wr(0x101C66, t & 0xFF)
    wr(0x101C67, t >> 8)
    wr(0x101C68, (m68 & 0xE0) | 1)                     # mode 1: codes (bits 8-11 in 0x101C67 low nibble)
    hi0 = rd(0x101C67) & 0xF0
    cur_hi = None
    for code, attr in tiles:
        if code >> 8 != cur_hi:
            cur_hi = code >> 8
            wr(0x101C67, hi0 | cur_hi)
        wr(0x101C66, code & 0xFF)
    wr(0x101C68, m68)
    for k, (code, attr) in enumerate(tiles):
        print('window %d col %d row %d: code %#05x attribute %02X' % (w, col + k, row, code, attr))

ap = argparse.ArgumentParser(description='OSD font/tile experiments (diag-osd)')
sub = ap.add_subparsers(dest='cmd', required=True)
sub.add_parser('info')
sub.add_parser('glyphs')
sub.add_parser('load')
p = sub.add_parser('row'); p.add_argument('row', type=int)
p = sub.add_parser('ddcrow'); p.add_argument('row', type=int)
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
elif a.cmd in ('load', 'row'):
    val = 0x100 if a.cmd == 'load' else 0x200 | (a.row & 0x7F)
    for _ in range(3 * TRIES):
        c0 = rd(0x2024B2)
        vset(0xEE, val)
        time.sleep(0.5)
        if rd(0x2024B2) != c0:
            print('%s done' % a.cmd)
            break
    else:
        sys.exit('%s: no reaction (diag-osd v3 in the build? DDC/CI working?)' % a.cmd)
elif a.cmd == 'ddcrow':
    geo = window(a.win)
    print('window %d: tile base %#06x, pitch %d' % (a.win, geo[0], geo[1]))
    tiles = [(6, 0x21)]                                # marker: solid base glyph 6
    tiles += [(0x3B0, x) for x in (0x21, 0x12, 0x2F, 0xF2, 0x40, 0x04, 0x84, 0xC8)]
    tiles += [(0, 0x21)] + [(0x3B1 + k, 0x21) for k in range(3)] + [(0, 0x21), (0x3CF, 0x21), (6, 0x21)]
    k = 0
    while k < len(tiles):                                # one run per code-high value (the firmware never
        n = k                                            # changes 0x101C67 within a run)
        while n < len(tiles) and tiles[n][0] >> 8 == tiles[k][0] >> 8:
            n += 1
        run(a.win, a.col + k, a.row, tiles[k:n], geo)
        k = n
else:
    run(a.win, a.col, a.row, [(a.code, a.attr)])
