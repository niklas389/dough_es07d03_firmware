# SPDX-License-Identifier: GPL-3.0-only
import sys, os, pickle, collections, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aeondis as A
"""Build an xref database (constants, call sites, insn owner) from funcs.pkl.

Usage: xrefs.py IMAGE BASE funcs.pkl xrefs.pkl
"""

def build(path, base, funcs_pkl, out):
    data = open(path, 'rb').read()
    funcs = pickle.load(open(funcs_pkl, 'rb'))
    owner = {}
    for f, v in funcs.items():
        for a in v['insns']:
            if a not in owner or f > owner[a]: owner[a] = f  # innermost-ish
    allins = sorted(owner)
    consts = collections.defaultdict(list)   # value -> [(addr, func)]
    calls = collections.defaultdict(list)    # target -> [(addr, func)]
    hi = {}
    prev = None
    for a in allins:
        x = A.decode(data, a - base, a)
        if prev is not None and a != prev: hi = {}
        prev = a + x['len']
        m = x['mnem']; v = x['vals']
        if m == 'b.movhi':
            k = [k for k in v if k != 'D'][0]
            hi[v['D'][1]] = (v[k][1] & 0xffff) << 16
            consts[hi[v['D'][1]]].append((a, owner[a]))
            continue
        if m in ('b.ori', 'b.addi') and 'A' in v and 'D' in v and v['A'][1] in hi:
            lo = [v[k][1] for k in v if k not in ('D', 'A')][0]
            val = (hi[v['A'][1]] + (lo if m == 'b.addi' else lo & 0xffff)) & 0xffffffff
            consts[val].append((a, owner[a]))
            hi.pop(v['A'][1], None)
            continue
        if m in ('b.ori','b.addi','b.movi') and 'A' in v and v['A'][1] == 0:
            lo = [v[k][1] for k in v if k not in ('D', 'A')][0]
            consts[(lo & 0xffff) if m=='b.ori' else lo & 0xffffffff].append((a, owner[a]))
        if m == 'b.jal':
            calls[x['target']].append((a, owner[a]))
        if 'D' in v and v['D'][0] == 'reg':
            hi.pop(v['D'][1], None)
    pickle.dump(dict(consts=dict(consts), calls=dict(calls), owner=owner), open(out, 'wb'))
if __name__ == '__main__':
    build(sys.argv[1], int(sys.argv[2], 0), sys.argv[3], sys.argv[4])
