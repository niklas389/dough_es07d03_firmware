#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Function discovery for AEON R2 images.

Recursive descent from trusted seeds: entry points, code pointers stored in a
data range, and movhi/ori constants that point at a function prologue. Switch
tables of the form movhi/addi table; slli; add; lwz; jr are followed.

Usage: funcs.py IMAGE BASE CODE_LO CODE_HI OUT.pkl DATA_LO DATA_HI ENTRY...
Example (main firmware runtime image):
  funcs.py runtime_0x200000.bin 0x200000 0x200000 0x2ae000 funcs.pkl \
           0x2ae000 0x453e78 0x26f528 0x2a7af4
"""
import sys, os, pickle, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aeondis as A
COND = {'b.beq','b.beqi','b.bf','b.bgts','b.bgtsi','b.bgtu','b.bgtui','b.bles','b.blesi','b.bleu',
        'b.bleui','b.bne','b.bnei','b.bnf'}

class Image:
    def __init__(self, data, base):
        self.d = data; self.base = base; self.end = base + len(data)
        self.cache = {}
    def ins(self, a):
        x = self.cache.get(a)
        if x is None:
            if not (self.base <= a < self.end): return None
            x = A.decode(self.d, a - self.base, a)
            self.cache[a] = x
        return x
    def u32(self, a, le=True):
        o = a - self.base
        return int.from_bytes(self.d[o:o+4], 'little' if le else 'big')


def is_prologue(img, a):
    x = img.ins(a)
    if not x or not x['name']: return False
    v = x['vals']
    if x['mnem'] == 'b.addi' and v.get('D', (0, -1))[1] == 1 and v.get('A', ('reg', 1))[1] == 1:
        imm = [v[k][1] for k in v if k not in ('D', 'A')]
        return bool(imm) and imm[0] < 0
    return False

def switch_targets(img, a, lo, hi):
    """Resolve 'movhi/addi table; add; lwz; jr' switch at a. Return list of targets or None."""
    back = []
    p = a
    # walk back linearly by trying previous instruction lengths
    for _ in range(14):
        for l in (2, 3, 4):
            x = img.ins(p - l)
            if x and x['name'] and x['len'] == l:
                p -= l; back.append((p, x)); break
        else:
            break
    tbl = None; n = None; hi_ = {}
    for q, x in reversed(back):
        v = x['vals']; m = x['mnem']
        if m == 'b.movhi':
            k = [k for k in v if k != 'D'][0]; hi_[v['D'][1]] = (v[k][1] & 0xffff) << 16
        elif m in ('b.ori', 'b.addi') and 'A' in v and 'D' in v and v['A'][1] in hi_:
            l = [v[k][1] for k in v if k not in ('D', 'A')][0]
            tbl = (hi_.pop(v['A'][1]) + (l if m == 'b.addi' else l & 0xffff)) & 0xffffffff
        elif m in ('b.sfgtui', 'b.bgtui', 'b.sfgeui'):
            imm = [v[k][1] for k in v if v[k][0] == 'imm']
            if imm: n = (imm[0] & 0xffff) + (1 if m != 'b.sfgeui' else 0)
    if tbl is None or n is None or n > 512 or not (img.base <= tbl < img.end): return None
    out = []
    for i in range(n):
        t = img.u32(tbl + 4 * i)
        if lo <= t < hi: out.append(t)
        else: return out or None
    return out

def explore(img, entry, lo, hi, fstarts):
    seen = set(); calls = set(); todo = [entry]; bad = False; jr = []; tails = set()
    while todo:
        a = todo.pop()
        while True:
            if a in seen: break
            if a != entry and a in fstarts: tails.add(a); break
            if not (lo <= a < hi): bad = True; break
            x = img.ins(a)
            if x is None or x['name'] is None: bad = True; break
            seen.add(a)
            m = x['mnem']; n = a + x['len']
            if m == 'b.jal': calls.add(x['target']); a = n; continue
            if m in COND: todo.append(x['target']); a = n; continue
            if m == 'b.j': a = x['target']; continue
            if m == 'b.jr':
                if x['vals']['A'][1] != 9:
                    t = switch_targets(img, a, lo, hi)
                    if t: todo.extend(t)
                    else: jr.append(a)
                break
            if m in ('b.return', 'b.reti', 'b.creti', 'b.cnreti', 'b.rfe'): break
            a = n
    return seen, calls, bad, jr, tails

def run(path, base, lo, hi, entries, extra_ptr_ranges):
    data = open(path, 'rb').read(); img = Image(data, base)
    seeds = set(entries)
    # code pointers stored in data (LE words) that land on a prologue
    for rlo, rhi in extra_ptr_ranges:
        for o in range(rlo - base, rhi - base - 3):
            w = int.from_bytes(data[o:o+4], 'little')
            if lo <= w < hi and is_prologue(img, w): seeds.add(w)
    fstarts = set(seeds); funcs = {}
    changed = True
    while changed:
        changed = False
        todo = sorted(fstarts - set(funcs))
        for f in todo:
            seen, calls, bad, jr, tails = explore(img, f, lo, hi, fstarts)
            funcs[f] = dict(insns=seen, calls=calls, bad=bad, jr=jr, tails=tails)
            for c in calls | tails:
                if lo <= c < hi and c not in fstarts: fstarts.add(c); changed = True
            # constants in code that point to prologues (function pointers)
            hi_ = {}
            for a in sorted(seen):
                x = img.ins(a); v = x['vals']; m = x['mnem']
                if m == 'b.movhi':
                    k = [k for k in v if k != 'D'][0]; hi_[v['D'][1]] = (v[k][1] & 0xffff) << 16
                elif m in ('b.ori', 'b.addi') and 'A' in v and 'D' in v and v['A'][1] in hi_:
                    l = [v[k][1] for k in v if k not in ('D', 'A')][0]
                    val = (hi_.pop(v['A'][1]) + (l if m == 'b.addi' else l & 0xffff)) & 0xffffffff
                    if lo <= val < hi and val not in fstarts and is_prologue(img, val):
                        fstarts.add(val); changed = True
    # re-explore all with final fstarts so bodies stop at other function starts
    for f in list(funcs):
        seen, calls, bad, jr, tails = explore(img, f, lo, hi, fstarts)
        funcs[f] = dict(insns=sorted(seen), calls=sorted(calls), bad=bad, jr=jr, tails=sorted(tails))
    return funcs

if __name__ == '__main__':
    path, base, lo, hi, out = sys.argv[1], int(sys.argv[2], 0), int(sys.argv[3], 0), int(sys.argv[4], 0), sys.argv[5]
    dlo, dhi = int(sys.argv[6], 0), int(sys.argv[7], 0)
    entries = [int(x, 0) for x in sys.argv[8:]]
    funcs = run(path, base, lo, hi, entries, [(dlo, dhi)])
    pickle.dump(funcs, open(out, 'wb'))
    cov = set()
    for v in funcs.values(): cov |= set(v['insns'])
    print('functions', len(funcs), 'bad', sum(v['bad'] for v in funcs.values()), 'insns', len(cov),
          'jr-switch', sum(len(v['jr']) for v in funcs.values()))
