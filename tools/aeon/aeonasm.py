#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Minimal AEON R2 assembler for small firmware patches.

Instructions are written with explicit vendor opcode names (as in isa_r2.json)
and keyword operands, so there is no syntax ambiguity:

    ('bg.movhi', dict(D=7, U=0x45))
    ('bg.lbz',   {'?': 6, 'A': 7, '!': 0x51cc})
    ('bg.bnei',  {'A': 6, 'I': 0, ';': 'label'})
    ('bg.j',     {'/': 0x245919})
    'label:'

Branch/jump operands (pc-relative letters) take an absolute address or a
label; the assembler converts them to offsets. assemble() returns the bytes,
and the caller is expected to verify them with aeondis.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_T = json.load(open(os.path.join(_HERE, 'isa_r2.json')))
OPS = {o['name']: o for o in _T['opcodes']}
LET = {l['letter']: l for l in _T['letters']}
F_PCREL = 0x8


def _length(name):
    return len(OPS[name]['encoding'].replace(' ', '')) // 8


def encode(name, fields, addr):
    enc = OPS[name]['encoding'].replace(' ', '')
    bits = ['0' if c == '-' else c for c in enc]
    pos = {}
    for i, c in enumerate(enc):
        if c not in '01-':
            pos.setdefault(c, []).append(i)
    if set(fields) != set(pos):
        raise ValueError('%s needs fields %s, got %s' % (name, sorted(pos), sorted(fields)))
    for c, v in fields.items():
        l = LET[c]
        if l['flags'] & F_PCREL:
            v = v - addr
        v = (v - l['add'])
        if v & ((1 << l['shift']) - 1):
            raise ValueError('%s: %s value not aligned' % (name, c))
        v >>= l['shift']
        w = len(pos[c])
        signed = l['flags'] & 2
        lo, hi = (-(1 << (w - 1)), (1 << (w - 1)) - 1) if signed else (0, (1 << w) - 1)
        if not lo <= v <= hi:
            raise ValueError('%s: %s=%#x out of range for %d bits' % (name, c, v, w))
        for p, ch in zip(pos[c], format(v & ((1 << w) - 1), '0%db' % w)):
            bits[p] = ch
    return int(''.join(bits), 2).to_bytes(len(enc) // 8, 'big')


def assemble(prog, base):
    """prog: list of 'label:' strings and (opcode_name, fields) tuples."""
    labels, a = {}, base
    for item in prog:
        if isinstance(item, str):
            name = item.rstrip(':')
            if name in labels:
                raise ValueError('duplicate label %r' % name)
            labels[name] = a
        else:
            a += _length(item[0])
    out, a = b'', base
    for item in prog:
        if isinstance(item, str):
            continue
        name, fields = item
        f = {k: (labels[v] if isinstance(v, str) else v) for k, v in fields.items()}
        b = encode(name, f, a)
        out += b
        a += len(b)
    return out, labels
