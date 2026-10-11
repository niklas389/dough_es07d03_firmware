#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Annotated listing of a function or address range.

Environment: IMG (default runtime_0x200000.bin), BASE (0x200000), FUNCS, XREFS.
Optional names.txt: 'ADDR NAME' per line.
Usage: fdis.py FUNC_ADDR_HEX | fdis.py START_HEX END_HEX
"""
import sys, os, pickle, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aeondis as A
IMG = os.environ.get('IMG', 'runtime_0x200000.bin'); BASE = int(os.environ.get('BASE', '0x200000'), 0)
FP = os.environ.get('FUNCS', 'funcs.pkl'); XP = os.environ.get('XREFS', 'xrefs.pkl')
data = open(IMG, 'rb').read()
funcs = pickle.load(open(FP, 'rb')); xr = pickle.load(open(XP, 'rb'))
names = {}
if os.path.exists('names.txt'):
    for l in open('names.txt'):
        l = l.split('#')[0].split()
        if len(l) >= 2: names[int(l[0], 16)] = l[1]
def nm(a):
    return names.get(a, 'sub_%x' % a)
def cstr(a):
    o = a - BASE
    if not (0 <= o < len(data)): return None
    e = data.find(b'\0', o, o + 200)
    if e <= o: return None
    s = data[o:e]
    if all(32 <= c < 127 or c in (9, 10, 13) for c in s) and len(s) >= 3:
        return s.decode().replace('\n', '\\n').replace('\r', '\\r')
    return None
def show(lo, hi=None, insns=None):
    hi_ = {}
    addrs = insns if insns is not None else None
    if addrs is None:
        addrs = []; a = lo
        while a < hi:
            x = A.decode(data, a - BASE, a); addrs.append(a); a += x['len']
    prev = None
    for a in addrs:
        if prev is not None and a != prev: print('        ...')
        x = A.decode(data, a - BASE, a); prev = a + x['len']
        ann = ''
        m = x['mnem']; v = x['vals']
        if a in names: print('%s:' % names[a])
        if m == 'b.movhi':
            k = [k for k in v if k != 'D'][0]; hi_[v['D'][1]] = (v[k][1] & 0xffff) << 16
        elif m in ('b.ori', 'b.addi') and 'A' in v and 'D' in v and v['A'][1] in hi_:
            lo_ = [v[k][1] for k in v if k not in ('D', 'A')][0]
            val = (hi_.pop(v['A'][1]) + (lo_ if m == 'b.addi' else lo_ & 0xffff)) & 0xffffffff
            s = cstr(val)
            ann = '; =0x%x' % val + (' "%s"' % s[:60] if s else '') + (' <%s>' % names[val] if val in names else '')
        if x['target'] is not None:
            t = x['target']
            ann = '; ' + (nm(t) if m == 'b.jal' or t in names else '')
        sys.stdout.write('%08x: %-12s %-9s %-28s %s\n' % (a, data[a-BASE:a-BASE+x['len']].hex(' '), m, x['ops'], ann))
if __name__ == '__main__':
    a = int(sys.argv[1], 16)
    if len(sys.argv) > 2:
        show(a, int(sys.argv[2], 16))
    else:
        f = funcs[a]
        callers = xr['calls'].get(a, [])
        print('; function %s  insns=%d  callers=%s' % (nm(a), len(f['insns']), ' '.join('%x(%s)' % (c, nm(g)) for c, g in callers[:12])))
        show(a, insns=f['insns'])
