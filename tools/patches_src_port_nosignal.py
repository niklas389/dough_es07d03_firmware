#!/usr/bin/env python3
"""Source of patches/port-nosignal.json (v2). Run in an unpacked work dir (RT=runtime_0x200000.bin).

Shorter "no signal" decision for the DP and HDMI input ports, for a faster
automatic input scan and a faster "No signal"; the USB-C port keeps the
vendor time.

Vendor (sub_260E0E -> sub_23E5C5, port +0x1A; see port-accept for +0x18):
the port monitor sub_23B068 (every 20 ms per port) declares a port without
signal after +0x1A passes (port state 2, flags +0x1C |= 6). sub_260E0E loops
over the 6 ports (port index in r3 at every sub_23E5C5 call) and chooses the
values by port type:
- type 0x20 (port 0 = front-end id 7 = USB-C, port 1 = id 8 = DP; measured
  2026-10-07 from the PM51 wake port: USB-C wake -> 0, DP wake -> 1):
  400 passes = 8 s (200 when settings +0x48 bit 2 or flg bit 0 is set);
- type bit 3/4/0x400 (ports 2-5, HDMI class): 500 passes = 10 s (200 with
  the flag);
- types bit 0 and bit 1/2 (20 / 60 passes) do not occur in the port table.
LG 28MQ780 (same SDK) uses 100 passes (2 s) for both classes.

v1 set all four values to NOSIG (200 = 4 s). With a USB-C source behind a
dock the monitor then woke, showed "No signal" and went back to standby,
twice in a row (2026-10-07); the dock delivers its stream later than a GPU
on DP. v2 therefore leaves port 0 at the vendor value:
- ports 2-5: both values -> NOSIG (as v1);
- type 0x20 values in sub_260E0E unchanged (400 / 200);
- the sub_23E5C5 call of the type-0x20 branch (0x260EE1) goes through a stub
  that sets r5 = NOSIG for port DP_PORT (1) only, then jumps to sub_23E5C5.
Default NOSIG 200 (4 s), the vendor's own flag-case value; not lower: on a
power-key start the DP signal arrived ~2 s after the port started searching.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

NOSIG = int(os.environ.get('NOSIG', '200'))
assert 50 <= NOSIG <= 255
DP_PORT = 1
SET_THR = 0x23E5C5                 # sub_23E5C5(port r3, accept r4, nosig r5)
HOOK = 0x260EE1                    # type-0x20 branch: jal sub_23E5C5
STUB = 0x203970                    # linker padding after bl-supply-off (0x203940-0x203968), before panel-prepower (0x203A00)

SITES = [  # addr, stock bytes, register, vendor value, what
 (0x260E70, '50e0c8', 7, 200, 'type bit3/4/0x400, flag case (cmov source)'),
 (0x260E73, 'c8a001f4', 5, 500, 'type bit3/4/0x400, normal case'),
]
edits = []
for a, old, reg, val, what in SITES:
    ob = cur(a, len(old) // 2)
    assert ob.hex() == old, (hex(a), ob.hex())
    x = A.decode(ob, 0, a)
    assert x['mnem'] == 'b.ori' and x['ops'] == 'r%d,r0,%#x' % (reg, val), x
    nb = (S.encode('bn.ori', {'D': reg, 'A': 0, 'N': NOSIG}, a) if len(ob) == 3 else
          S.encode('bg.ori', {'D': reg, 'A': 0, 't': NOSIG}, a))
    assert len(nb) == len(ob) and A.decode(nb, 0, a)['ops'] == 'r%d,r0,%#x' % (reg, NOSIG)
    print('%06x: %s -> %s  %s %d -> %d passes' % (a, ob.hex(), nb.hex(), what, val, NOSIG))
    if nb != ob:
        edits.append({'addr': '0x%06X' % a, 'old': ob.hex(), 'new': nb.hex(),
                      'asm': 'sub_260E0E ori r%d,r0,%#x -> ori r%d,r0,%#x (port +0x1A no-signal threshold, %s)' % (reg, val, reg, NOSIG, what)})

# type-0x20 values stay vendor (checked), the call goes through the stub
assert cur(0x260ED1, 3).hex() == '50a0c8' and cur(0x260EDA, 4).hex() == 'c8a00190'
hx = A.decode(d, HOOK - 0x200000, HOOK)
assert hx['mnem'] == 'b.jal' and hx['target'] == SET_THR and hx['len'] == 4, hx
assert A.decode(d, 0x260E32 - 0x200000, 0x260E32)['ops'] == 'r3,r10'      # r3 = port index (extbz r3,r10), not changed before HOOK

prog = [
 'stub:',
 ('bg.bnei', {'A': 3, 'I': DP_PORT, ';': 'go'}),     # other type-0x20 port (0 = USB-C): vendor value
 ('bg.ori', {'D': 5, 'A': 0, 't': NOSIG}),           # DP: no-signal threshold NOSIG
 'go:',
 ('bg.j', {'/': SET_THR}),
]
code, L = S.assemble(prog, STUB)
assert STUB + len(code) <= 0x203A00 and cur(STUB, len(code)) == b'\0' * len(code)
for a, b, x in A.disasm(code, STUB, STUB + len(code), STUB):
    print('%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
hook = S.encode('bg.jal', {'/': STUB}, HOOK)
assert len(hook) == 4 and A.decode(hook, 0, HOOK)['target'] == STUB
edits.append({'addr': '0x%06X' % STUB, 'old': '00' * len(code), 'new': code.hex(),
              'asm': 'stub (linker padding 0x203970): if port r3 == %d (DP) r5 = %d; j sub_23E5C5' % (DP_PORT, NOSIG)})
edits.append({'addr': '0x%06X' % HOOK, 'old': cur(HOOK, 4).hex(), 'new': hook.hex(),
              'asm': 'sub_260E0E type-0x20 branch: jal sub_23E5C5 -> jal stub'})

patch = {
 'name': 'port-nosignal',
 'summary': ('Declare the DP and HDMI input ports "no signal" after %d x 20 ms = %.1f s instead of 8-10 s '
             '(faster automatic input scan and "No signal"); USB-C keeps the vendor 8 s') % (NOSIG, NOSIG * 0.02),
 'status': 'untested (v2)',
 'conflicts': ['port-nosignal-v1'],
 'edits': edits,
 'notes': ("Port +0x1A thresholds set by sub_260E0E (vendor: 400 passes for type 0x20 = ports 0 USB-C and 1 DP, 500 for "
           "types bit3/4/0x400 = ports 2-5, 200 in the flag case). v2: ports 2-5 -> %d; port 1 (DP) -> %d through a stub on "
           "the type-0x20 sub_23E5C5 call; port 0 (USB-C) unchanged (a dock delivers its stream later). LG 28MQ780 uses 100. "
           "Accept thresholds (+0x18, see port-accept) unchanged. Generated by tools/patches_src_port_nosignal.py (NOSIG=n, 50-255)."
           % (NOSIG, NOSIG)),
}
out = os.environ.get('OUT', 'port-nosignal.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
