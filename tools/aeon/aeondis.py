#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""MStar AEON R2 disassembler.

Table-driven: the opcode encodings, operand letters and display rules come from
isa_r2.json, which is derived from eb4x/ghidra-plugin-aeon (Apache-2.0). That
project generated them from the vendor toolchain's own tables and calibrated
them against the vendor objdump.

Usage: aeondis.py IMAGE START END [BASE]
  START/END are addresses; BASE is the address of the first byte of IMAGE.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Operand letter flags (from the vendor tables)
F_REG = 0x1
F_SIGNED = 0x2
F_PCREL = 0x8

# Decode-priority constraints: these encodings belong to another opcode when
# the register field is r0 (bt.trap/bt.nop, b.pclwz).
_NONZERO_REG = {'bt.stack', 'bn.lbz', 'bg.lbz', 'bg.lbs'}


def _load():
    t = json.load(open(os.path.join(_HERE, 'isa_r2.json')))
    letters = {l['letter']: l for l in t['letters']}
    bylen = {16: [], 24: [], 32: []}
    for o in t['opcodes']:
        enc = o['encoding'].replace(' ', '')
        n = len(enc)
        ign = set(o['ignored_bits'])
        mask = val = 0
        fields = {}
        for i, ch in enumerate(enc):
            bit = n - 1 - i
            if ch == '-' and i not in ign:
                ch = '0'          # don't-care bits the decoder really checks
            if ch in '01':
                mask |= 1 << bit
                if ch == '1':
                    val |= 1 << bit
            elif ch != '-':
                fields.setdefault(ch, []).append(bit)
        if n in bylen:
            bylen[n].append(dict(name=o['name'], mnem=o['display'], args=o['args'], mask=mask,
                                 val=val, fields=fields, unit=o['unit'], dup=o['dup_first']))
    return letters, bylen


LETTERS, BYLEN = _load()


def insn_len(b0):
    """Length from the top three bits of the first byte: 0xx=3, 100=2, 101/11x=4."""
    t = b0 >> 5
    return 3 if t < 4 else 2 if t == 4 else 4


def _field(word, bits):
    v = 0
    for b in bits:
        v = (v << 1) | ((word >> b) & 1)
    return v


def _operand(letter, raw, nbits, addr):
    L = LETTERS.get(letter)
    if L is None:
        return ('imm', raw)
    if L['flags'] & F_REG:
        return ('reg', raw)
    v = raw
    if L['flags'] & F_SIGNED and raw & (1 << (nbits - 1)):
        v = raw - (1 << nbits)
    v = (v << L['shift']) + L['add']
    if L['flags'] & F_PCREL:
        return ('pc', (addr + v) & 0xffffffff)
    return ('imm', v)


def decode(data, off, addr=None):
    """Decode one instruction at data[off]; addr is its address (default off).

    Returns a dict: len, mnem, ops, name, unit, vals {letter: (kind, value)},
    target (branch/call target or None). mnem is '.invalid' if nothing matched.
    """
    if addr is None:
        addr = off
    if off >= len(data):
        return None
    n = insn_len(data[off])
    if off + n > len(data):
        return None
    word = int.from_bytes(data[off:off + n], 'big')
    for o in BYLEN[n * 8]:
        if word & o['mask'] != o['val']:
            continue
        vals = {ch: _operand(ch, _field(word, bits), len(bits), addr) for ch, bits in o['fields'].items()}
        if o['name'] in _NONZERO_REG and vals.get('?', ('reg', 1))[1] == 0:
            continue
        out, target, a, i = [], None, o['args'], 0
        while i < len(a):
            ch = a[i]
            if ch == 'r' and i + 1 < len(a) and vals.get(a[i + 1], ('', 0))[0] == 'reg':
                out.append('r%d' % vals[a[i + 1]][1]); i += 2; continue
            if ch in vals:
                k, v = vals[ch]
                if k == 'pc':
                    out.append('0x%x' % v); target = v
                elif k == 'reg':
                    out.append('r%d' % v)
                else:
                    out.append('-0x%x' % -v if v < 0 else '0x%x' % v)
            else:
                out.append(ch)
            i += 1
        if o['dup'] and out:
            out = [out[0], ','] + out
        return dict(len=n, mnem=o['mnem'], ops=''.join(out), name=o['name'], unit=o['unit'],
                    vals=vals, target=target)
    return dict(len=n, mnem='.invalid', ops='', name=None, unit=None, vals={}, target=None)


def disasm(data, start, end, base=0):
    """Linear sweep over [start, end) given as addresses; yields (addr, bytes, insn)."""
    a = start
    while a < end:
        x = decode(data, a - base, a)
        if x is None:
            break
        yield a, data[a - base:a - base + x['len']], x
        a += x['len']


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    data = open(sys.argv[1], 'rb').read()
    start, end = int(sys.argv[2], 0), int(sys.argv[3], 0)
    base = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0
    for a, b, x in disasm(data, start, end, base):
        print('%08x: %-12s %-10s %s' % (a, b.hex(' '), x['mnem'], x['ops']))


if __name__ == '__main__':
    main()
