#!/usr/bin/env python3
"""ES07D03 (MStar MST9U4) firmware package tool.

Works on the vendor USB/ISP update package, e.g.
ES07D03_Beta03_rev1169-E771_USB_update.bin (flashed at SPI 0x400000).

  es07fw.py info    PKG                 print layout and check all checksums
  es07fw.py unpack  PKG OUTDIR          extract runtime image and components
  es07fw.py patch   PKG OUT NAME...     apply patches from patches/*.json, repack
  es07fw.py list                        list available patches
  es07fw.py diff    PKG OUT             show runtime-image and PM51 differences

The main firmware runs from DRAM. Its first 0x3800 bytes (vectors, startup)
are stored uncompressed at package offset 0x30080. The rest is raw deflate
starting at 0x33880 and is inflated by the bootloader to 0x203800. Together
they form the "runtime image", linked at 0x200000. Patch addresses in
patches/*.json are runtime addresses, or PM51 code addresses for patches with
"space": "pm51" (PM51 code runs from flash at package offset 0x10080).

Repacking keeps every package offset unchanged. The new deflate stream is
written at 0x33880 and zero-padded up to the original stream end. The size
trailer, header CRC and package CRC are then recomputed.
"""
import glob
import json
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
PATCH_DIR = os.path.join(os.path.dirname(HERE), 'patches')

PKG_SIZE = 0x148474
HDR = 0x10000            # image header (little-endian u32 fields)
HEAD_OFF = 0x30080       # main image start (header +0x00)
HEAD_LEN = 0x3800        # uncompressed head copied to the load address
Z_OFF = HEAD_OFF + HEAD_LEN
LOAD = 0x200000          # header +0x04
PM51_OFF = 0x10080       # PM51 8051 code, executed from flash; code address 0 = this offset
PM51_LEN = 0x10000
REF_SHA256 = 'd9be1e1c7aad81813faa7490a200fe6cfb83d0f371169f4ff94b829ea64c5ce3'


def crc32_msb(data, crc=0):
    """CRC-32, poly 0x04C11DB7, MSB-first (not reflected), init 0, no final xor.

    This is what the MST9U BDMA CRC engine computes; both image checks use it.
    """
    tbl = _tbl()
    for b in data:
        crc = ((crc << 8) & 0xffffffff) ^ tbl[(crc >> 24) ^ b]
    return crc


_T = None


def _tbl():
    global _T
    if _T is None:
        _T = []
        for i in range(256):
            r = i << 24
            for _ in range(8):
                r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
            _T.append(r & 0xffffffff)
    return _T


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


class Package:
    def __init__(self, data):
        self.d = bytearray(data)
        h = self.hdr = struct.unpack_from('<8I', self.d, HDR)
        # +00 main start, +04 load addr, +08 load end, +0C main end,
        # +14 CRC over [main start, main end), +20 package length w/o trailer
        self.main_start, self.load, self.load_end, self.main_end = h[0], h[1], h[2], h[3]
        self.main_crc = h[5]
        self.total = u32(self.d, HDR + 0x20)
        # head +0x114a: main length (main_end - main_start)
        self.main_len = u32(self.d, self.main_start + 0x114a)
        # stream trailer: u32 inflated size at main_end - 6, then 2 unchecked bytes
        self.size_off = self.main_end - 6
        self.inflated_size = u32(self.d, self.size_off)

    def check(self):
        errs = []
        if len(self.d) != self.total + 4:
            errs.append('length %#x != header total %#x + 4' % (len(self.d), self.total))
        if (self.main_start, self.load) != (HEAD_OFF, LOAD):
            errs.append('unexpected main start/load address')
        if self.main_end - self.main_start != self.main_len:
            errs.append('head length field mismatch')
        if self.load_end != self.load + self.main_len:
            errs.append('load end mismatch')
        if self.d[self.main_start + 0x1147:self.main_start + 0x114a] != b'\xbe\xad\xde':
            errs.append('head magic DEADBE missing')
        c = crc32_msb(self.d[self.main_start:self.main_end])
        if c != self.main_crc:
            errs.append('main CRC %08x != header %08x' % (c, self.main_crc))
        c = crc32_msb(self.d[:self.total])
        if c != struct.unpack_from('>I', self.d, self.total)[0]:
            errs.append('package CRC mismatch (computed %08x)' % c)
        return errs

    def runtime(self):
        """Return (runtime image bytes, deflate stream length)."""
        o = zlib.decompressobj(-15)
        body = o.decompress(bytes(self.d[Z_OFF:self.size_off]))
        if not o.eof or len(body) != self.inflated_size:
            raise ValueError('deflate stream did not end cleanly')
        zlen = (self.size_off - Z_OFF) - len(o.unused_data)
        return bytes(self.d[HEAD_OFF:Z_OFF]) + body, zlen

    def rebuild(self, rt):
        """Replace the runtime image; recompress and fix every checksum."""
        head, body = rt[:HEAD_LEN], rt[HEAD_LEN:]
        if len(body) != self.inflated_size:
            raise ValueError('runtime image size changed')
        c = zlib.compressobj(9, zlib.DEFLATED, -15, 8)
        z = c.compress(body) + c.flush()
        room = self.size_off - Z_OFF
        if len(z) > room:
            raise ValueError('compressed main image too large: %#x > %#x' % (len(z), room))
        # self-check: the stream must inflate back to exactly the new body
        if zlib.decompress(z, -15) != body:
            raise ValueError('recompression round-trip failed')
        self.d[HEAD_OFF:Z_OFF] = head
        self.d[Z_OFF:self.size_off] = z + b'\0' * (room - len(z))
        crc = crc32_msb(self.d[self.main_start:self.main_end])
        struct.pack_into('<I', self.d, HDR + 0x14, crc)
        struct.pack_into('>I', self.d, self.total, crc32_msb(self.d[:self.total]))
        self.main_crc = crc
        return len(z)


def load_patches():
    out = {}
    for p in sorted(glob.glob(os.path.join(PATCH_DIR, '*.json'))):
        j = json.load(open(p))
        j['file'] = os.path.basename(p)
        out[j['name']] = j
    return out


def is_pm51(p):
    return p.get('space') == 'pm51'


def apply_patch(rt, p):
    """Apply a runtime-image patch to rt, or a PM51 patch to the package bytes."""
    rt = bytearray(rt)
    base = -PM51_OFF if is_pm51(p) else LOAD
    for e in p['edits']:
        a = int(e['addr'], 16) - base
        old, new = bytes.fromhex(e['old']), bytes.fromhex(e['new'])
        if len(old) != len(new):
            raise ValueError('%s: old/new length differ' % p['name'])
        cur = bytes(rt[a:a + len(old)])
        if cur == new:
            continue
        if cur != old:
            raise ValueError('%s @%s: found %s, expected %s' % (p['name'], e['addr'], cur.hex(), old.hex()))
        rt[a:a + len(old)] = new
    return bytes(rt)


def cmd_info(pkg_path):
    import hashlib
    raw = open(pkg_path, 'rb').read()
    p = Package(raw)
    sha = hashlib.sha256(raw).hexdigest()
    print('package      %s  %d bytes' % (pkg_path, len(raw)))
    print('sha256       %s%s' % (sha, '  (stock Beta03)' if sha == REF_SHA256 else ''))
    build = p.d[0x31280:0x31294].split(b'\0')
    print('build        %s %s' % (build[0].decode(), build[1].decode() if len(build) > 1 else ''))
    print('main image   %#x..%#x  load %#x..%#x' % (p.main_start, p.main_end, p.load, p.load_end))
    rt, zlen = p.runtime()
    print('deflate      %#x..%#x (%#x bytes) -> %#x bytes at %#x' %
          (Z_OFF, Z_OFF + zlen, zlen, p.inflated_size, LOAD + HEAD_LEN))
    print('runtime      %#x..%#x' % (LOAD, LOAD + len(rt)))
    errs = p.check()
    print('checksums    ' + ('OK (main CRC %08x, package CRC %08x)' %
                             (p.main_crc, struct.unpack_from('>I', p.d, p.total)[0]) if not errs else
                             'FAIL: ' + '; '.join(errs)))
    applied = [n for n, q in load_patches().items() if patch_state(rt, q, bytes(p.d)) == 'applied']
    print('patches      ' + (', '.join(applied) if applied else 'none detected'))
    return 0 if not errs else 1


def patch_state(rt, p, pkg=None):
    if is_pm51(p):
        if pkg is None:
            return 'unknown'
        rt, base = pkg, -PM51_OFF
    else:
        base = LOAD
    st = set()
    for e in p['edits']:
        a = int(e['addr'], 16) - base
        cur = rt[a:a + len(bytes.fromhex(e['old']))]
        st.add('applied' if cur == bytes.fromhex(e['new']) else 'stock' if cur == bytes.fromhex(e['old']) else 'other')
    return st.pop() if len(st) == 1 else 'mixed'


def cmd_unpack(pkg_path, outdir):
    p = Package(open(pkg_path, 'rb').read())
    rt, _ = p.runtime()
    os.makedirs(outdir, exist_ok=True)
    parts = {
        'runtime_0x200000.bin': rt,
        'sboot_0x0.bin': p.d[0x0:0x10000],
        'pm51_0x10080.bin': p.d[0x10080:0x20000],
        'mcu51_0x20080.bin': p.d[0x20080:0x30000],
        'secu_r2_0x125d00.bin': p.d[0x125d00:0x139a00],
    }
    for n, b in parts.items():
        open(os.path.join(outdir, n), 'wb').write(b)
        print('%-24s %8d bytes' % (n, len(b)))


def cmd_patch(pkg_path, out_path, names):
    raw = open(pkg_path, 'rb').read()
    p = Package(raw)
    errs = p.check()
    if errs:
        sys.exit('input package fails checks: ' + '; '.join(errs))
    allp = load_patches()
    rt, _ = p.runtime()
    for n in names:
        if n not in allp:
            sys.exit('unknown patch %r (see: es07fw.py list)' % n)
        missing = [r for r in allp[n].get('requires', []) if r not in names]
        if missing:
            sys.exit('patch %r requires %s in the same build' % (n, ', '.join(missing)))
        clash = [c for c in allp[n].get('conflicts', []) if c in names]
        if clash:
            sys.exit('patch %r conflicts with %s (do not combine)' % (n, ', '.join(clash)))
    order = []                      # required patches first (some edit code their dependency added)
    def add(n):
        if n not in order:
            for r in allp[n].get('requires', []):
                add(r)
            order.append(n)
    for n in names:
        add(n)
    for n in order:
        if is_pm51(allp[n]):
            p.d[:] = apply_patch(bytes(p.d), allp[n])
        else:
            rt = apply_patch(rt, allp[n])
        print('applied %s' % n)
    pm = bytes(p.d[PM51_OFF:PM51_OFF + PM51_LEN])
    zlen = p.rebuild(rt)
    # verify the written package from scratch
    q = Package(bytes(p.d))
    errs = q.check()
    rt2, _ = q.runtime()
    if errs or rt2 != rt or bytes(q.d[PM51_OFF:PM51_OFF + PM51_LEN]) != pm:
        sys.exit('verification of rebuilt package failed: ' + '; '.join(errs))
    open(out_path, 'wb').write(p.d)
    print('wrote %s (deflate %#x bytes, main CRC %08x) - verified' % (out_path, zlen, q.main_crc))


def _diff(ra, rb, base, tag=''):
    i = 0
    while i < len(ra):
        if ra[i] != rb[i]:
            j = i
            while j < len(ra) and ra[j] != rb[j]:
                j += 1
            print('%s%08x: %s -> %s' % (tag, base + i, ra[i:j].hex(), rb[i:j].hex()))
            i = j
        else:
            i += 1


def cmd_diff(a_path, b_path):
    pa, pb = Package(open(a_path, 'rb').read()), Package(open(b_path, 'rb').read())
    ra, _ = pa.runtime()
    rb, _ = pb.runtime()
    if len(ra) != len(rb):
        sys.exit('runtime sizes differ')
    _diff(ra, rb, LOAD)
    _diff(pa.d[PM51_OFF:PM51_OFF + PM51_LEN], pb.d[PM51_OFF:PM51_OFF + PM51_LEN], 0, 'pm51 ')


def cmd_list():
    for n, p in load_patches().items():
        print('%-20s %s' % (n, p['summary']))


def main(argv):
    if len(argv) >= 3 and argv[1] == 'info':
        return cmd_info(argv[2])
    if len(argv) == 4 and argv[1] == 'unpack':
        return cmd_unpack(argv[2], argv[3])
    if len(argv) >= 5 and argv[1] == 'patch':
        return cmd_patch(argv[2], argv[3], argv[4:])
    if len(argv) == 4 and argv[1] == 'diff':
        return cmd_diff(argv[2], argv[3])
    if len(argv) == 2 and argv[1] == 'list':
        return cmd_list()
    sys.exit(__doc__)


if __name__ == '__main__':
    sys.exit(main(sys.argv) or 0)
