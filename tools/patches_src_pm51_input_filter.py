#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Source of patches/pm51-input-filter.json. Run in an unpacked work dir (PM=pm51_0x10080.bin).

PM51 standby controller: with a fixed input, a source wake reported by the
front-end (event 9) wakes the monitor only if the front-end reports activity
on the selected input. With "Select Automatically" nothing changes. This is
how the LG 28MQ780 PM51 (same SDK) handles port wakes.

Stock path (docs/firmware-map.md sections 21/22):
- The front-end (MSB3300) sends a serial frame (command 0xF0, message type 0)
  with a connector bit mask; 0x5F89 stores it in XDATA 0x6208 (32 bit, big
  endian) and the queue 0x61E9 becomes 9.
- The classifier 0x5BAA (run only by the sleep loop 0x9BA5) sets the event
  0x5E89 = 9 (0x5CF3), loads the mask into r4..r7 and calls 0x69B3 (0x5D05),
  which returns the first port whose front-end id (XDATA 0x6202+port) has its
  bit set in the mask, or 5 if none. Then it clears 0x6208 and 0x61E9 and
  reports an event (0x23 = 1). The wake decision 0x745A wakes on event 9
  unconditionally.
- Measured (diag-poke, RAM 0x453C74/0x453C78): DP wake -> event 9, port 1;
  USB-C wake -> event 9, port 0.
- The suppress list XDATA 0x5E81+port is filled from the main firmware's
  standby request (0x41A8 -> 0x95CB): settings +0x4F = 0 (automatic) -> all 0;
  fixed input -> 1 for every port except the selected one. +0x4F - 1 is the
  port index (sub_2678D9 -> sub_23F836(path, +0x4F - 1) sets the path's port).
  Stock uses the list only in the port finders 0x7D10/0x6E0A, and event 2
  wakes regardless of the result.

Patch: the call 0x5D05 lcall 0x69B3 -> lcall filt (bank-0 free space 0xA140;
pm51-wake-window uses 0xA100-0xA12A):
- not event 9 (0x61E9 != 9) or mask 0 -> 0x69B3 as stock;
- else the front-end ids of suppressed ports get bit 7 set (no id matches),
  0x69B3 runs, bit 7 is cleared again on all six ids (ids are < 0x20);
- result < 5, or 5 with port 5 not suppressed -> return the port (wake as
  stock; with automatic input nothing is suppressed, so the result is the
  stock one);
- result 5 with port 5 suppressed (no selected input in the mask) -> drop
  the event: return address discarded, 0x5E89 = 0, 0x6208 and 0x61E9 cleared
  (as the stock path does), continue at 0x5D1F (the classifier's tail, which
  returns 0x23 = 0: no event; the sleep loop keeps polling).
Keys, events other than 9 and the main firmware are not touched.
"""
import json, os, subprocess

d = open(os.environ.get('PM', 'pm51_0x10080.bin'), 'rb').read()
def cur(a, n): return d[a:a + n]

FILT = 0xA140
HOOK = 0x5D05
F_69B3, CLS_TAIL = 0x69B3, 0x5D1F
hi, lo = lambda a: (a >> 8) & 0xFF, lambda a: a & 0xFF

# tiny assembler: items are bytes or ('rel', label) (1-byte relative offset) or a label string
prog = [
 'filt',
 bytes([0x90, 0x61, 0xE9, 0xE0]),               # mov dptr,#0x61E9 ; movx a,@dptr
 bytes([0xB4, 0x09]), ('rel', 'stock'),          # cjne a,#9,stock
 bytes([0xEF, 0x4E, 0x4D, 0x4C]),                # mov a,r7 ; orl a,r6 ; orl a,r5 ; orl a,r4
 bytes([0x60]), ('rel', 'stock'),                # jz stock              (mask 0: as stock)
 bytes([0x7A, 0x00]),                            # mov r2,#0
 'mark',
 bytes([0x74, 0x81, 0x2A, 0xF5, 0x82, 0xE4, 0x34, 0x5E, 0xF5, 0x83, 0xE0]),  # a = XDATA[0x5E81+r2] (suppressed?)
 bytes([0x60]), ('rel', 'next1'),                # jz next1
 bytes([0x74, 0x02, 0x2A, 0xF5, 0x82, 0xE4, 0x34, 0x62, 0xF5, 0x83, 0xE0]),  # a = XDATA[0x6202+r2] (front-end id)
 bytes([0x44, 0x80, 0xF0]),                      # orl a,#0x80 ; movx @dptr,a   (hide the id)
 'next1',
 bytes([0x0A, 0xBA, 0x06]), ('rel', 'mark'),     # inc r2 ; cjne r2,#6,mark
 bytes([0x12, hi(F_69B3), lo(F_69B3)]),          # lcall 0x69B3          (r7 = port; r2 not used by it)
 bytes([0x7A, 0x00]),                            # mov r2,#0
 'unmark',
 bytes([0x74, 0x02, 0x2A, 0xF5, 0x82, 0xE4, 0x34, 0x62, 0xF5, 0x83, 0xE0]),  # a = XDATA[0x6202+r2]
 bytes([0x54, 0x7F, 0xF0]),                      # anl a,#0x7F ; movx @dptr,a   (restore)
 bytes([0x0A, 0xBA, 0x06]), ('rel', 'unmark'),   # inc r2 ; cjne r2,#6,unmark
 bytes([0xBF, 0x05]), ('rel', 'allow'),          # cjne r7,#5,allow      (an unsuppressed port matched)
 bytes([0x90, 0x5E, 0x86, 0xE0]),                # mov dptr,#0x5E86 ; movx a,@dptr   (port 5 suppressed?)
 bytes([0x60]), ('rel', 'allow'),                # jz allow
 'block',
 bytes([0xD0, 0xE0, 0xD0, 0xE0]),                # pop acc ; pop acc     (drop the return to 0x5D08)
 bytes([0xE4]),                                  # clr a
 bytes([0x90, 0x5E, 0x89, 0xF0]),                # 0x5E89 = 0            (no event)
 bytes([0x90, 0x62, 0x08, 0xF0, 0xA3, 0xF0, 0xA3, 0xF0, 0xA3, 0xF0]),  # 0x6208..0x620B = 0
 bytes([0x90, 0x61, 0xE9, 0xF0]),                # 0x61E9 = 0
 bytes([0x02, hi(CLS_TAIL), lo(CLS_TAIL)]),      # ljmp 0x5D1F
 'allow',
 bytes([0x22]),                                  # ret (r7 = port)
 'stock',
 bytes([0x02, hi(F_69B3), lo(F_69B3)]),          # ljmp 0x69B3
]

def assemble(prog, base):
    labels, a = {}, base
    for it in prog:
        if isinstance(it, str): labels[it] = a
        elif isinstance(it, tuple): a += 1
        else: a += len(it)
    out, a = bytearray(), base
    for it in prog:
        if isinstance(it, str): continue
        if isinstance(it, tuple):
            off = labels[it[1]] - (a + 1)
            assert -128 <= off <= 127, it
            out.append(off & 0xFF); a += 1
        else:
            out += it; a += len(it)
    return bytes(out), labels

blob, L = assemble(prog, FILT)
assert cur(FILT, len(blob)) in (b'', b'\xff' * len(blob)), cur(FILT, len(blob)).hex()
assert FILT >= 0xA12B                              # after pm51-wake-window (0xA100-0xA12A)

# stock code the patch relies on
assert cur(HOOK, 3).hex() == '1269b3'
assert cur(0x5CED, 0x35).hex().startswith('9061e9e0602c905e89f0906208'), cur(0x5CED, 13).hex()
assert cur(0x5D08, 0x17).hex() == '905e8aeff0906208121ee800000000e49061e9f0752301', cur(0x5D08, 0x17).hex()
assert cur(CLS_TAIL, 3).hex() == '905e87'           # classifier tail: mov dptr,#0x5E87
assert cur(0x4E60, 12).hex() == '74022bf582e43462f583e022'   # id table XDATA 0x6202+r3
assert cur(0x95D1, 3).hex() == '905e81'             # suppress list 0x5E81+port

hook = bytes([0x12, hi(FILT), lo(FILT)])

def dis(code, base):
    return subprocess.run(['rasm2', '-a', '8051', '-o', hex(base), '-D', code.hex()],
                          capture_output=True, text=True).stdout.strip()
print(dis(blob, FILT))
print('labels', {k: hex(v) for k, v in L.items()})
print('%04x  %s -> %s' % (HOOK, cur(HOOK, 3).hex(), hook.hex()))

patch = {
 'name': 'pm51-input-filter',
 'summary': ('PM51: with a fixed input, a source wake from the front-end (event 9) wakes the monitor only if the '
             'selected input is active; "Select Automatically" unchanged (LG 28MQ780 behaviour)'),
 'status': 'untested',
 'space': 'pm51',
 'edits': [
  {'addr': '0x%04X' % FILT, 'old': 'ff' * len(blob), 'new': blob.hex(),
   'asm': 'bank-0 free space 0xA140: filt (event 9: hide suppressed ports from 0x69B3; no unsuppressed match -> drop the event)'},
  {'addr': '0x%04X' % HOOK, 'old': cur(HOOK, 3).hex(), 'new': hook.hex(),
   'asm': 'classifier event-9 path: lcall 0x69B3 -> lcall filt'},
 ],
 'notes': ("Addresses are PM51 code addresses (bank 0, package offset 0x10080 + addr). Uses the stock suppress list "
           "XDATA 0x5E81+port (filled at the standby request from settings +0x4F) and the front-end id table XDATA "
           "0x6202+port. Event 9 with mask 0, events other than 9 and automatic input behave as stock. "
           "Generated by tools/patches_src_pm51_input_filter.py."),
}
out = os.environ.get('OUT', 'pm51-input-filter.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
