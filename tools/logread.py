#!/usr/bin/env python3
"""logread.py - read and decode the diag-log event log over DDC (needs diag-poke + diag-log).

    MON=1 SPECCTL=./specctl tools/logread.py

Prints the events oldest first: time (s since the firmware start), time since
the previous event, event, value. Read-only. The log lives in RAM: it starts
empty at every firmware start and holds the last 16 events.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPECCTL = os.environ.get('SPECCTL', 'specctl')
MON = os.environ.get('MON', '0')
P = json.load(open(os.path.join(HERE, '..', 'patches', 'diag-log.json')))
TAGS = {int(v, 16): k for k, v in P['tags'].items()}
NAMES = {'h_off': 'F panel off      caller', 'h_on': 'N panel on       caller',
         'h_sig': 'S OSD timer end  caller', 'h_st4': 'E state-4 entry  caller',
         'h_gate': 'G standby gate   result (1 = refused)',
         'm_init': 'I main init start', 'm_dev': 'D init done (EEPROM, scaler)',
         'm_loop': 'M main loop start', 'm_bl': 'B backlight on   caller',
         'h_mb': 'Q mailbox slow  ', 'h_port': 'P port state     ', 'h_path': 'Y input path     '}
CALLS = P.get('calls', {})
WATCH = P.get('watch', {})
MILESTONES = ('m_init', 'm_dev', 'm_loop')
BASE = int(P['data']['ms'], 16)
N = P['data']['entries']


def vcp(op, code, val=None):
    cmd = [SPECCTL, op, '0x%02X' % code] + ([str(val)] if val is not None else []) + ['-d', MON, '--fast']
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    m = re.search(r'= (\d+) ', out)
    return int(m.group(1)) if m else None


def read_bytes(addr, n):
    hi = (addr >> 16) & 0xFFFF
    for _ in range(4):
        vcp('set', 0xEA, hi)
        if vcp('get', 0xEA) == hi:
            break
    else:
        sys.exit('address high half not accepted (is diag-poke in this build?)')
    out = []
    for a in range(addr, addr + n):
        lo, v = a & 0xFFFF, None
        for _ in range(4):
            vcp('set', 0xEB, lo)
            if vcp('get', 0xEB) != lo:
                continue
            v = vcp('get', 0xEC)
            if v is not None and v <= 0xFF:
                break
            v = None
        if v is None:
            sys.exit('read failed at %#x' % a)
        out.append(v)
        print('\rreading %d/%d' % (a - addr + 1, n), end='', file=sys.stderr)
    print(file=sys.stderr)
    return bytes(out)


raw = read_bytes(BASE, 8 + 8 * N)
u32 = lambda o: int.from_bytes(raw[o:o + 4], 'little')
now, count = u32(0), u32(4)
print('firmware running for %.3f s, %d events logged' % (now / 1000, count))
keep_first = P.get('keep_first', False)
first = 0 if keep_first else max(0, count - N)
if count > N:
    print('(%s %d of %d events shown)' % ('first' if keep_first else 'last', N, count))
prev = None
for i in range(first, min(count, first + N)):
    o = 8 + 8 * (i % N)
    t, w = u32(o), u32(o + 4)
    tag, val = w >> 24, w & 0xFFFFFF
    t_name = TAGS.get(tag, '')
    if t_name.startswith('c_') and t_name in CALLS:
        name = 'C done sub_%s (call at 0x%s)' % (CALLS[t_name][2:].upper(), t_name[2:].upper())
    elif t_name.startswith('c_'):
        name = 'C done sub_%s' % t_name[2:].upper()
    else:
        name = NAMES.get(t_name, 'tag %02X' % tag)
    dt = '' if prev is None else '+%.3f' % ((t - prev) / 1000)
    if t_name == 'h_gate':
        shown = '%d' % val
    elif t_name == 'h_mb':
        if 'mailbox_window_ms' in P:
            name = 'Q mailbox cmd   '
            shown = '0x%02X sub %2d  data[0] 0x%02X' % (val >> 16, (val >> 12) & 0xF, (val >> 4) & 0xFF)
        else:
            shown = 'cmd 0x%02X sub %d took %d ms' % (val >> 16, (val >> 12) & 0xF, (val & 0xFFF) * 2)
    elif t_name == 'w_lp':
        w = WATCH.get('0x%04X' % (val >> 8), {})
        name = 'W %-16s' % w.get('addr', '?')
        shown = '= 0x%02X   (%s)' % (val & 0xFF, w.get('what', 'entry 0x%04X' % (val >> 8)))
    elif t_name in ('h_port', 'h_path'):
        shown = '%d -> state %d' % ((val >> 8) & 0xFF, val & 0xFF)
    elif t_name in MILESTONES or t_name.startswith('c_'):
        shown = ''
    else:
        shown = '0x%06X' % val
    print('%10.3f s %10s  %s %s' % (t / 1000, dt, name, shown))
    prev = t
