#!/usr/bin/env python3
"""Source of patches/pm51-wake-window.json. Run in an unpacked work dir (PM=pm51_0x10080.bin).

PM51 standby controller: port activity wakes the monitor as in the stock
firmware, except during the first WAKE_WINDOW seconds after the main firmware
requested standby. Replaces pm51-wake-recheck (do not combine the two).

Why: the stock port-wake check 0x9D54 is a stub (always wake), so the AUX
traffic that GPU/dock produce right at standby entry woke the monitor again
(kernel log 2026-10-02: ~27 IRQ_HPD in the second of the entry, monitor back
within 3 s). pm51-wake-recheck answered that by waking only if the activity
bits (PM 0x0386 bit 5, 0x038B bits 2:0) were still set 200 ms later; that
loses one-shot events: a USB-C source behind a dock did not wake the monitor
at all (2026-10-07, stock firmware woke).

The stock firmware already filters by input: at power-save entry the main
firmware sends a port mask (block 0x48A740 +4, from settings +0x4F: fixed
input -> only that port may wake; automatic input -> all ports), which the
PM51 copies to its suppress list 0x5E81+port (0x41A8 -> 0x95CB). The same
scheme is used by the LG 28MQ780 PM51.

Time base: XDATA 0x5E5E is incremented once per second by the PM51 task
0x880F (also while asleep: the sleep loop 0x9BA5 runs it) and is otherwise
only cleared at PM51 start (0x9D88); nothing reads it.

Patch (bank-0 code, free space from 0xA100; 0xA000 is used by pm51-wake-recheck):
- 0x882C: the increment of 0x5E5E saturates at 255 (no wrap, so the window
  cannot reopen every 256 s).
- 0x41A8 (standby request from the main firmware, after the port mask is
  applied): 0x5E5E = 0. Only this path re-arms the window; re-entering sleep
  after an ignored event does not, so a source that keeps trying still wakes
  the monitor once the window has passed.
- 0x9D54 (event 2 check in the wake decision 0x745A): same scratch writes as
  the stub; returns 1 (wake) if 0x5E5E >= WAKE_WINDOW, else 0 (stay asleep).
Keys and the other wake events do not pass through 0x9D54.
"""
import sys, json, os, subprocess

d = open(os.environ.get('PM', 'pm51_0x10080.bin'), 'rb').read()
def cur(a, n): return d[a:a + n]

W = int(os.environ.get('WAKE_WINDOW', '5'))
assert 2 <= W <= 60
SAT, REQ, WIN = 0xA100, 0xA10B, 0xA114
hi, lo = lambda a: (a >> 8) & 0xFF, lambda a: a & 0xFF

sat = bytes([0x90, 0x5E, 0x5E,          # mov dptr,#0x5E5E
             0xE0,                      # movx a,@dptr
             0xB4, 0xFF, 0x01,          # cjne a,#0xFF,+1
             0x22,                      # ret               (saturated)
             0x04,                      # inc a
             0xF0,                      # movx @dptr,a
             0x22])                     # ret
req = bytes([0x12, 0x95, 0xCB,          # lcall 0x95CB      (replaced call: apply the port mask)
             0xE4,                      # clr a
             0x90, 0x5E, 0x5E,          # mov dptr,#0x5E5E
             0xF0,                      # movx @dptr,a      (window starts)
             0x22])                     # ret
win = bytes([0x75, 0x24, 0x00,          # mov 0x24,#0x00    (stub scratch writes)
             0x75, 0x25, 0xC8,          # mov 0x25,#0xC8
             0xE4,                      # clr a
             0xF5, 0x26,                # mov 0x26,a
             0x90, 0x5E, 0x5E,          # mov dptr,#0x5E5E
             0xE0,                      # movx a,@dptr
             0xC3,                      # clr c
             0x94, W,                   # subb a,#W
             0x7F, 0x00,                # mov r7,#0         (inside the window: stay asleep)
             0x40, 0x02,                # jc +2
             0x7F, 0x01,                # mov r7,#1         (wake)
             0x22])                     # ret
assert SAT + len(sat) == REQ and REQ + len(req) == WIN
blob = sat + req + win
assert cur(SAT, len(blob)) in (b'', b'\xff' * len(blob)), cur(SAT, len(blob)).hex()   # dump may end before 0xA000

hooks = [  # addr, expected stock bytes, new bytes, what
 (0x882C, '905e5ee004f0', bytes([0x12, hi(SAT), lo(SAT), 0x00, 0x00, 0x00]),
  '1 s task: inc 0x5E5E -> lcall sat (saturating at 255); nop nop nop'),
 (0x41A8, '1295cb', bytes([0x12, hi(REQ), lo(REQ)]),
  'standby request (state 3, command 1): lcall 0x95CB -> lcall req (port mask, then 0x5E5E = 0)'),
 (0x9D54, '752400', bytes([0x02, hi(WIN), lo(WIN)]),
  'event-2 check stub -> ljmp win (wake only after the window)'),
]
for a, old, new, _ in hooks:
    assert cur(a, len(old) // 2).hex() == old, (hex(a), cur(a, len(old) // 2).hex())
    assert len(new) == len(old) // 2

def dis(code, base):
    out = subprocess.run(['rasm2', '-a', '8051', '-o', hex(base), '-D', code.hex()], capture_output=True, text=True).stdout
    return out.strip()
print(dis(blob, SAT))
for a, old, new, what in hooks:
    print('%04x  %s -> %s   %s' % (a, old, new.hex(), dis(new, a).replace('\n', ' | ')))

edits = [{'addr': '0x%04X' % SAT, 'old': 'ff' * len(blob), 'new': blob.hex(),
          'asm': 'bank-0 free space: sat (0xA100), req (0xA10B), win (0xA114, window %d s)' % W}]
for a, old, new, what in hooks:
    edits.append({'addr': '0x%04X' % a, 'old': old, 'new': new.hex(), 'asm': what})
patch = {
 'name': 'pm51-wake-window',
 'summary': 'PM51: port activity wakes the monitor as in stock, except during the first %d s after standby entry (ignores the AUX burst caused by the entry itself); replaces pm51-wake-recheck' % W,
 'status': 'untested',
 'space': 'pm51',
 'conflicts': ['pm51-wake-recheck'],
 'edits': edits,
 'notes': ("Addresses are PM51 code addresses (bank 0, package offset 0x10080 + addr). Time base: XDATA 0x5E5E, "
           "+1 per second by the PM51 task 0x880F (also while asleep), otherwise unused; made saturating at 255. "
           "Window starts when the main firmware's standby request is processed (0x41A8). The stock port mask "
           "(fixed input: only that port wakes; automatic input: all ports) is unchanged. "
           "Generated by tools/patches_src_pm51_wake_window.py (WAKE_WINDOW=n, 2-60)."),
}
out = os.environ.get('OUT', 'pm51-wake-window.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
