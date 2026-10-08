#!/usr/bin/env python3
"""logread.py - read and decode the diag-log event log over DDC (needs diag-poke + diag-log).

    MON=1 SPECCTL=./specctl tools/logread.py
    LOG=diag-log-mb MON=1 SPECCTL=./specctl tools/logread.py   (for a diag-log-mb build)

Prints the events oldest first: time (s since the firmware start), time since
the previous event, event, value. Read-only. The log lives in RAM: it starts
empty at every firmware start; the number of entries and whether the first or
the last ones are kept come from patches/diag-log.json. Only the entries in
use are read.
"""
import json, os, re, subprocess, sys

import shutil
HERE = os.path.dirname(os.path.abspath(__file__))
SPECCTL = os.environ.get('SPECCTL', 'specctl')
if not shutil.which(SPECCTL):
    sys.exit("specctl not found as '%s': set SPECCTL=/path/to/specctl" % SPECCTL)
MON = os.environ.get('MON', '0')
P = json.load(open(os.path.join(HERE, '..', 'patches', os.environ.get('LOG', 'diag-log') + '.json')))
TAGS = {int(v, 16): k for k, v in P['tags'].items()}
NAMES = {'h_off': 'F panel off      caller', 'h_on': 'N panel on       caller',
         'h_sig': 'S OSD timer end  caller', 'h_st4': 'E state-4 entry  caller',
         'h_gate': 'G standby gate   result (1 = refused)',
         'm_init': 'I main init start', 'm_dev': 'D init done (EEPROM, scaler)',
         'm_loop': 'M main loop start', 'm_bl': 'B backlight on   caller',
         'm_fe': 'X front-end set-up done (sub_261FA8)', 'm_prep': 'R panel preparation returned',
         'h_mb': 'Q mailbox slow  ', 'h_sel': 'U input select   ', 'h_mbf': 'K MAILBOX FAILED ', 'h_port': 'P port state     ', 'h_path': 'Y input path     '}
# front-end commands (docs/firmware-map.md sections 19, 24, 26); ids: 7 USB-C, 8 DP, 0x0B HDMI 1, 0x0C HDMI 2, 0 unused
FEID = {7: 'USB-C', 8: 'DP', 0x0B: 'HDMI 1', 0x0C: 'HDMI 2', 0: 'unused port'}
fe = lambda i: FEID.get(i, 'id 0x%02X' % i)
MBNAMES = {(0x20, 14): lambda a, b: 'HPD %s %s' % (fe(a), 'low' if b == 0 else 'high'),
           (0x20, 3): lambda a, b: 'HPD level %s = %d' % (fe(a), b),
           (0x20, 0): lambda a, b: 'port configuration / enable',
           (0x20, 12): lambda a, b: 'configuration update %s' % ('begin' if a else 'end'),
           (0x60, 2): lambda a, b: 'port setting %s = %d' % (fe(a), b)}
# input selection sub_2678D9: settings +0x4F value and the callers (low 16 bits of the return address)
INPUTS = {0: 'automatic', 1: 'USB-C', 2: 'DP', 3: 'HDMI 1', 4: 'HDMI 2'}
SELCALLERS = {0x92C7: 'sub_258E5D (OSD/key task, applies 0x457857)', 0x7A67: 'OSD action sub_267A36',
              0x7AEC: 'OSD action sub_267A7F', 0x7C37: 'OSD action sub_267C06',
              0x84CE: 'start-up sub_268453', 0x84E2: 'start-up sub_268453 (path 1)',
              0x9CD5: 'profile restore sub_269AA4', 0xE437: 'sub_26E279'}
CALLS = P.get('calls', {})
WATCH = P.get('watch', {})
MILESTONES = ('m_init', 'm_dev', 'm_loop', 'm_fe', 'm_prep')
BASE = int(P['data']['ms'], 16)
N = P['data']['entries']
TRIES = int(os.environ.get('TRIES', '4'))   # raise when DDC/CI answers only now and then


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
    for _ in range(TRIES):
        vcp('set', 0xEA, hi)
        if vcp('get', 0xEA) == hi:
            break
    else:
        sys.exit('address high half not accepted (is diag-poke in this build?)')
    out = []
    for a in range(addr, addr + n):
        lo, v = a & 0xFFFF, None
        for _ in range(TRIES):
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


raw = read_bytes(BASE, 8)
u32 = lambda o: int.from_bytes(raw[o:o + 4], 'little')
now, count = u32(0), u32(4)
used = min(count, N)
raw += read_bytes(BASE + 8, 8 * used) if used else b''

# A DDC read now and then returns a wrong byte (seen: one time stamp byte read as 0).
# Entries are written in time order, so an entry whose time is out of order is read again.
def order(first, last):
    ts = [u32(8 + 8 * (i % N)) for i in range(first, last)]
    tg = [raw[8 + 8 * (i % N) + 7] for i in range(first, last)]           # unknown tag byte: read error too
    return [k for k in range(len(ts)) if (k > 0 and ts[k] < ts[k - 1]) or (k + 1 < len(ts) and ts[k] > ts[k + 1])
            or tg[k] not in TAGS]
first0 = 0 if P.get('keep_first', False) else max(0, count - N)
last0 = min(count, first0 + N)
for _ in range(2):
    bad = order(first0, last0)
    if not bad or len(bad) > 8:
        break
    raw = bytearray(raw)
    for k in bad:
        o = 8 + 8 * ((first0 + k) % N)
        raw[o:o + 8] = read_bytes(BASE + o, 8)
    raw = bytes(raw)
SUSPECT = set(first0 + k for k in order(first0, last0))
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
    elif t_name == 'h_mb' and P.get('q_format') == 'cmd_sub_dur':
        name = 'Q mailbox done  '
        d = val & 0xFF
        shown = '0x%02X sub %2d  took %s ms' % (val >> 16, (val >> 8) & 0xFF, '>=255' if d == 255 else d)
    elif t_name == 'h_mb' and P.get('q_format') == 'cmd_sub_data0':
        name = 'Q mailbox cmd   '
        shown = '0x%02X sub %2d  data[0] 0x%02X' % (val >> 16, (val >> 8) & 0xFF, val & 0xFF)
    elif t_name == 'h_mb' and P.get('q_format') == 'cmd_d1_sub_data0':
        name = 'Q mailbox cmd   '
        c, sb, d0, d1 = (val >> 16) & 0xF0, (val >> 8) & 0xFF, val & 0xFF, (val >> 16) & 0x0F
        shown = '0x%02X sub %2d  data 0x%02X %X' % (c, sb, d0, d1)
        what = MBNAMES.get((c, sb))
        if what:
            shown += '   (%s)' % what(d0, d1)
    elif t_name == 'h_mb':
        if 'mailbox_window_ms' in P:
            name = 'Q mailbox cmd   '
            shown = '0x%02X sub %2d  data[0] 0x%02X' % (val >> 16, (val >> 12) & 0xF, (val >> 4) & 0xFF)
        else:
            shown = 'cmd 0x%02X sub %d took %d ms' % (val >> 16, (val >> 12) & 0xF, (val & 0xFFF) * 2)
    elif t_name == 'q_hdr':
        name = 'Q cmd            '
        shown = '0x%02X sub %2d  length %d' % (val >> 16, (val >> 8) & 0xFF, val & 0xFF)
    elif t_name == 'q_dat':
        name = '    data         '
        shown = '%02X %02X %02X' % (val >> 16, (val >> 8) & 0xFF, val & 0xFF)
    elif t_name == 'h_mbf':
        shown = '0x%02X sub %2d  (no answer from the PM51 / front-end within the 10 s budget)' % (val >> 16, (val >> 8) & 0xFF)
    elif t_name == 'h_sel':
        c = val & 0xFFFF
        shown = 'path %d  +0x4F = %d (%s)  by %s' % (val >> 20 & 0xF, val >> 16 & 0xF,
                 INPUTS.get(val >> 16 & 0xF, '?'), SELCALLERS.get(c, 'return address ..%04X' % c))
    elif t_name in ('w_lp', 'w_run'):
        w = WATCH.get('0x%04X' % (val >> 8), {})
        name = 'W %-16s' % w.get('addr', '?')
        shown = '= 0x%02X   (%s)' % (val & 0xFF, w.get('what', 'entry 0x%04X' % (val >> 8)))
    elif t_name in ('h_port', 'h_path'):
        shown = '%d -> state %d' % ((val >> 8) & 0xFF, val & 0xFF)
    elif t_name in MILESTONES or t_name.startswith('c_'):
        shown = ''
    else:
        shown = '0x%06X' % val
    if i in SUSPECT:
        shown += '   [time or tag inconsistent: read error, or the log changed while it was read]'
    print('%10.3f s %10s  %s %s' % (t / 1000, dt, name, shown))
    prev = t
