#!/usr/bin/env python3
"""logread.py - read and decode the diag-log event log over DDC (needs diag-poke + a diag-log variant).

    tools/logread.py                       read the log (default LOG=diag-log-ring)
    tools/logread.py -n 20                 read only the newest 20 entries (faster)
    tools/logread.py -i dump.json          decode a saved dump, no monitor needed
    LOG=diag-log-mb MON=1 SPECCTL=./specctl TRIES=10 tools/logread.py

Prints the events oldest first: time (s since the firmware start), time since
the previous event, event, value. Read-only. The log lives in RAM: it starts
empty at every firmware start; the number of entries and whether the first or
the last ones are kept come from patches/<LOG>.json.

Robustness (DDC/CI answers only now and then while the monitor changes power
state): a byte that cannot be read is retried (TRIES, default 4), then left
out; the reading goes on and stops only after many failures in a row
(--maxfail, default 12) or Ctrl-C. Whatever was read is decoded: unreadable
entries are listed as such. Entries are read newest first, so an early stop
still shows the latest events. The raw bytes are saved as JSON (default
/tmp/logread-last.json, -o to choose) and can be decoded again with -i.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(description='read and decode the diag-log event log')
ap.add_argument('-n', type=int, default=None, help='read only the newest N entries')
ap.add_argument('-o', default=os.path.join(tempfile.gettempdir(), 'logread-last.json'), help='save the raw dump here')
ap.add_argument('-i', default=None, help='decode a saved dump instead of reading the monitor')
ap.add_argument('--maxfail', type=int, default=12, help='stop after this many unreadable bytes in a row')
args = ap.parse_args()

LOGNAME = os.environ.get('LOG', 'diag-log-ring')
SPECCTL = os.environ.get('SPECCTL', 'specctl')
MON = os.environ.get('MON', '0')
TRIES = int(os.environ.get('TRIES', '4'))   # raise when DDC/CI answers only now and then
dump = json.load(open(args.i)) if args.i else None
if dump:
    LOGNAME = dump.get('log', LOGNAME)
P = json.load(open(os.path.join(HERE, '..', 'patches', LOGNAME + '.json')))
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
           (0x60, 2): lambda a, b: 'port setting %s = %d' % (fe(a), b),
           (0x60, 255): lambda a, b: 'link query %s (standby gate / diag-fe)' % fe(a)}
# input selection sub_2678D9: settings +0x4F value and the callers (low 16 bits of the return address)
INPUTS = {0: 'automatic', 1: 'USB-C', 2: 'DP', 3: 'HDMI 1', 4: 'HDMI 2'}
SELCALLERS = {0x92C7: 'sub_258E5D (OSD/key task, applies 0x457857)', 0x7A67: 'OSD action sub_267A36',
              0x7AEC: 'OSD action sub_267A7F', 0x7C37: 'OSD action sub_267C06',
              0x84CE: 'start-up sub_268453', 0x84E2: 'start-up sub_268453 (path 1)',
              0x9CD5: 'profile restore sub_269AA4', 0xE437: 'sub_26E279',
              0x18B7: 'picture-watchdog recovery', 0x1338: 'wake-port-first (start-up)'}
CALLS = P.get('calls', {})
WATCH = P.get('watch', {})
MILESTONES = ('m_init', 'm_dev', 'm_loop', 'm_fe', 'm_prep')
BASE = int(P['data']['ms'], 16)
N = P['data']['entries']
KEEP_FIRST = P.get('keep_first', False)


def plausible(w):
    tag, val = w >> 24, w & 0xFFFFFF
    if tag not in TAGS:
        return False
    if TAGS[tag] in ('w_lp', 'w_run') and WATCH and '0x%04X' % (val >> 8) not in WATCH:
        return False
    return True



# ---------------------------------------------------------------- reading
def vcp(op, code, val=None):
    cmd = [SPECCTL, op, '0x%02X' % code] + ([str(val)] if val is not None else []) + ['-d', MON, '--fast']
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    m = re.search(r'= (\d+) ', out)
    return int(m.group(1)) if m else None


class Reader:
    def __init__(self):
        self.hi, self.fails, self.stopped = None, 0, None

    def set_hi(self, hi):
        for _ in range(TRIES):
            vcp('set', 0xEA, hi)
            if vcp('get', 0xEA) == hi:
                self.hi = hi
                return True
        self.hi = None
        return False

    def byte(self, a):
        """One byte, or None after TRIES attempts (the address high half is set again on trouble)."""
        hi, lo = (a >> 16) & 0xFFFF, a & 0xFFFF
        for attempt in range(TRIES):
            if self.hi != hi or attempt == TRIES // 2:
                if not self.set_hi(hi):
                    continue
            vcp('set', 0xEB, lo)
            if vcp('get', 0xEB) != lo:
                time.sleep(0.1 * attempt)
                continue
            v = vcp('get', 0xEC)
            if v is not None and v <= 0xFF:
                self.fails = 0
                return v
            time.sleep(0.1 * attempt)
        self.fails += 1
        if self.fails >= 3:
            time.sleep(1.0)               # DDC/CI gone for a moment (power state change): give it time
        return None

    def block(self, a, n):
        out = []
        for k in range(n):
            if self.stopped:
                out.append(None)
                continue
            v = self.byte(a + k)
            out.append(v)
            if self.fails >= args.maxfail:
                self.stopped = '%d unreadable bytes in a row (last at %#x)' % (self.fails, a + k)
        return out


u32 = lambda b: None if b is None or None in b else int.from_bytes(bytes(b), 'little')
slots = {}            # ring slot -> 8 byte values (None = unreadable)
notes = []
if dump:
    hdr, slots = dump['header'], {int(k): v for k, v in dump['slots'].items()}
    hdr_end = dump.get('header_end')
    notes += dump.get('notes', [])
else:
    if not shutil.which(SPECCTL):
        sys.exit("specctl not found as '%s': set SPECCTL=/path/to/specctl" % SPECCTL)
    R = Reader()
    hdr, hdr_end = R.block(BASE, 8), None
    count0 = u32(hdr[4:8])
    if count0 is None:
        notes.append('event counter unreadable: reading all %d slots, order by time' % N)
        want = list(range(N - 1, -1, -1))
    else:
        first = 0 if KEEP_FIRST else max(0, count0 - N)
        last = min(count0, first + N)
        want = [i % N for i in range(last - 1, first - 1, -1)]          # newest first
    if args.n is not None:
        want = want[:args.n]
    try:
        for k, s in enumerate(want):
            if R.stopped:
                break
            slots[s] = R.block(BASE + 8 + 8 * s, 8)
            print('\rreading entry %d/%d (%d unreadable bytes so far)' % (
                k + 1, len(want), sum(v is None for e in slots.values() for v in e)), end='', file=sys.stderr)
    except KeyboardInterrupt:
        notes.append('reading interrupted (Ctrl-C) after %d of %d entries' % (len(slots), len(want)))
    print(file=sys.stderr)
    # an entry out of time order or with an unknown tag/watch address: DDC read error, read it again (twice at most)
    def suspects():
        seq = [s for s in reversed(want) if s in slots and None not in slots[s]]
        ts = [u32(slots[s][0:4]) for s in seq]
        return [s for k, s in enumerate(seq) if (k and ts[k] < ts[k - 1]) or (k + 1 < len(seq) and ts[k] > ts[k + 1])
                or not plausible(u32(slots[s][4:8]))]
    for _ in range(2):
        sus = suspects() if count0 is not None else []
        if not sus or len(sus) > 8 or R.stopped:
            break
        for s in sus:
            slots[s] = R.block(BASE + 8 + 8 * s, 8)
    if R.stopped:
        notes.append('reading stopped: %s; %d of %d entries read' % (R.stopped, len(slots), len(want)))
    if not R.stopped:
        R.fails = 0
        hdr_end = R.block(BASE, 8)                                      # did events arrive meanwhile?
    try:
        json.dump({'log': LOGNAME, 'base': '%#x' % BASE, 'entries': N, 'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                   'header': hdr, 'header_end': hdr_end, 'slots': {str(k): v for k, v in slots.items()},
                   'notes': notes}, open(args.o, 'w'))
        notes.append('raw dump saved to %s (decode again with -i)' % args.o)
    except OSError as e:
        notes.append('raw dump not saved: %s' % e)

# ---------------------------------------------------------------- decoding
def decode(t, w):
    tag, val = w >> 24, w & 0xFFFFFF
    t_name = TAGS.get(tag, '')
    if t_name.startswith('c_') and t_name in CALLS:
        name = 'C done sub_%s (call at 0x%s)' % (CALLS[t_name][2:].upper(), t_name[2:].upper())
    elif t_name.startswith('c_'):
        name = 'C done sub_%s' % t_name[2:].upper()
    else:
        name = NAMES.get(t_name, 'tag %02X' % tag)
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
        wt = WATCH.get('0x%04X' % (val >> 8), {})
        name = 'W %-16s' % wt.get('addr', '?')
        shown = '= 0x%02X   (%s)' % (val & 0xFF, wt.get('what', 'entry 0x%04X' % (val >> 8)))
    elif t_name in ('h_port', 'h_path'):
        shown = '%d -> state %d' % ((val >> 8) & 0xFF, val & 0xFF)
    elif t_name in MILESTONES or t_name.startswith('c_'):
        shown = ''
    else:
        shown = '0x%06X' % val
    return name, shown


now, count = u32(hdr[0:4]), u32(hdr[4:8])
now_end, count_end = (u32(hdr_end[0:4]), u32(hdr_end[4:8])) if hdr_end else (None, None)
print('firmware running for %s s, %s events logged' % (
    '?' if now is None else '%.3f' % (now / 1000), '?' if count is None else count))
if count is not None and count_end is not None and count_end != count:
    if count_end < count:
        notes.append('event counter went DOWN during the read (%d -> %d): the firmware restarted, entries mix two runs'
                     % (count, count_end))
    else:
        notes.append('%d new events arrived while the log was read: the oldest slots may hold newer entries; '
                     'shown in time order' % (count_end - count))
if count is not None and count > N:
    print('(%s %d of %d events kept)' % ('first' if KEEP_FIRST else 'last', N, count))

# ring order (oldest first) when the counter is known and nothing arrived meanwhile, else time order
rows, bad = [], []
if count is not None:
    first = 0 if KEEP_FIRST else max(0, count - N)
    order = [i % N for i in range(first, min(count, first + N))]
else:
    order = sorted(slots)
for s in order:
    if s not in slots:
        continue
    e = slots[s]
    t, w = u32(e[0:4]), u32(e[4:8])
    if t is None or w is None:
        bad.append(s)
        rows.append((s, t, None))
    else:
        rows.append((s, t, w))
by_time = count is None or (count_end is not None and count_end != count)
if by_time:
    rows.sort(key=lambda r: (r[1] is None, r[1] or 0))
times = [r[1] for r in rows if r[2] is not None]
prev = None
for k, (s, t, w) in enumerate(rows):
    if w is None:
        print('%10s   %10s  ? unreadable entry (slot %d)%s' % ('?' if t is None else '%.3f s' % (t / 1000), '', s,
              '' if t is None else ', time readable'))
        continue
    name, shown = decode(t, w)
    # an entry out of time order is a read error, or the log changed while it was read
    odd = (k and rows[k - 1][2] is not None and rows[k - 1][1] > t) or \
          (k + 1 < len(rows) and rows[k + 1][2] is not None and rows[k + 1][1] < t) or not plausible(w)
    if odd:
        shown += '   [entry inconsistent: read error, or the log changed while it was read]'
    dt = '' if prev is None else '+%.3f' % ((t - prev) / 1000)
    print('%10.3f s %10s  %s %s' % (t / 1000, dt, name, shown))
    prev = t
if bad:
    notes.append('%d entries could not be read completely' % len(bad))
for n in notes:
    print('note: ' + n)
