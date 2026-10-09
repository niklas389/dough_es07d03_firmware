#!/usr/bin/env python3
"""Source of patches/pm51-hold-link.json. Run in an unpacked work dir (PM=pm51_0x10080.bin).

PM51 standby controller, Option A of docs/firmware-map.md sections 51-55:
deep standby while a DP-class source holds its link, with the input
front-end left running so the link stays up (DisplayPort: the sink keeps the
main-link receiver active while the source keeps the link), and the
standby controller watching for video itself.

Requested by the main firmware (gate-all-dp v5): block byte +3 of the
standby request (PM51 XDATA 0x5E95, unused by stock) = 0x80 | connectors
whose source held the link (bit 0 USB-C = port 0 / front-end id 7, bit 1
DP = port 1 / id 8). Without that byte the standby is stock.

Stock standby entry (0x4A29, state 1): ... 0x78FF (front-end check), then
0x8A25(3) = front-end command 0x00 sub 1 with mode 3 and the wake mask
(IRAM 0x28..0x2B): the front-end leaves its normal program for the
low-power one, which drops the DP link (section 53); a dock retrains it
and the activity wakes the monitor again (sections 22, 36).

Patch (bank-0 code at 0xA200, state in free XDATA 0x7F00-0x7F11; XDATA RAM
is 0x5000-0x7FFF per the startup code 0x2AD5, used up to 0x634A and 0x7337):
- 0x4AF1 'mov dptr,#0x5E97' -> lcall pre: hold off (H_ON = 0), then the
  replaced instruction. Every standby entry starts without hold.
- 0x4B1A 'lcall 0x8A25' -> lcall mode: hold flag set -> do not send mode 3
  (front-end stays in mode 0, link kept); save the wake mask, H_ON = 1.
  Otherwise stock.
- 0x9BB0 'lcall 0x880F' (sleep loop) -> lcall sec: counts the PM51's
  one-second flag (bit 0x21.0, set by the timer ISR 0x25E5, cleared in
  0x880F) into H_TICK, then 0x880F.
- 0x9BB9 'lcall 0x5BAA' (sleep loop, event classifier) -> lcall poll: the
  classifier first (keys and all stock events unchanged); then, in hold and
  standby state (0x5E6A = 1), once per second:
  1. link query of both DP-class connectors (front-end command 0x60, sub
     0xFF, x 0x0B, data [id]; the vendor standby gate's query: 0 = source
     active, 1 = none);
  2. a connector that is active and was not held -> wake (event 9, port);
     not for a connector in the suppress list 0x5E81+port (fixed input,
     as pm51-input-filter);
  3. stream width (MSA, section 54) of DP decoders 0-2, high byte at front-end
     0x11306D/0x11316D/0x11326D (front-end command 0xFF, sub 0xFF, x 2 = its
     register read): non-zero (width >= 256) -> wake, event 9, port of the
     held connector (5 when both are held: the main firmware then selects as
     stock);
  4. no connector active any more -> release: mode 3 with the saved mask
     (the stock deep standby, 1.2 W), hold off;
  5. three rounds in a row with a query that got no answer -> release too.
  The wake uses the stock event path: 0x5E89 = 9, 0x5E8A = port, 0x23 = 1,
  r7 = 1; the wake decision 0x745A wakes on event 9 unconditionally.
Front-end transfers use the stock frame routine 0x64A4 (r7 cmd, r5 sub,
r3 x, IRAM 0x36.. lengths and generic pointers as at 0x98B6/0x83E4).

Unchanged: keys, the stock events (port activity, front-end messages),
power-off (state 2), standby without the hold byte.
Not verified on hardware (first build): that the PM51's frames reach the
front-end's normal program in the standby clock mode, and that the
front-end keeps decoding MSA while the scaler is unpowered. Both fail safe:
no answer -> release to stock deep standby after 3 s; no MSA -> the monitor
stays dark until a key (or the link is released).
"""
import json, os, subprocess

d = open(os.environ.get('PM', 'pm51_0x10080.bin'), 'rb').read()
def cur(a, n): return d[a:a + n]
hi, lo = lambda a: (a >> 8) & 0xFF, lambda a: a & 0xFF

BASE = 0xA200
XB = 0x7F00
H_ON, H_MASK, H_TICK, H_LAST, H_FAIL, H_ACT, H_NF = (XB + i for i in range(7))
H_SAVE, TXB, RXB = XB + 0x08, XB + 0x0C, XB + 0x10
FLAG = 0x5E95                       # block byte +3 (main firmware), unused by stock
F_8A25, F_64A4, F_5BAA, F_880F = 0x8A25, 0x64A4, 0x5BAA, 0x880F
HOOKS = {0x4AF1: ('905e97', 'pre'), 0x4B1A: ('128a25', 'mode'), 0x9BB0: ('12880f', 'sec'),
         0x9BB9: ('125baa', 'poll')}
ACC7, BIT_SEC = 0xE7, 0x08          # bit addresses: ACC.7, 0x21.0

def dptr(a): return bytes([0x90, hi(a), lo(a)])
def xset(a, v): return dptr(a) + bytes([0x74, v, 0xF0])          # XDATA[a] = v
LC = lambda lab: ('abs', 0x12, lab)                              # lcall label/address
LJ = lambda lab: ('abs', 0x02, lab)                              # ljmp label/address
R = lambda lab: ('rel', lab)

prog = [
 # ---- pre: replaces 'mov dptr,#0x5E97' at 0x4AF1 ----
 'pre',
 bytes([0xE4]), dptr(H_ON), bytes([0xF0]),                     # H_ON = 0
 dptr(0x5E97), bytes([0x22]),

 # ---- mode: replaces 'lcall 0x8A25' at 0x4B1A (r7 = 3, wake mask in IRAM 0x28..0x2B) ----
 'mode',
 dptr(FLAG), bytes([0xE0]),
 bytes([0x20, ACC7]), R('hold'),                               # jb acc.7,hold
 LJ(F_8A25),
 'hold',
 bytes([0x54, 0x03, 0x70, 0x03]), LJ(F_8A25),                  # no connector bit -> stock
 dptr(H_MASK), bytes([0xF0]),
 xset(H_ON, 1),
 dptr(H_SAVE),
 bytes([0xE5, 0x28, 0xF0, 0xA3, 0xE5, 0x29, 0xF0, 0xA3, 0xE5, 0x2A, 0xF0, 0xA3, 0xE5, 0x2B, 0xF0]),
 bytes([0xE4]), dptr(H_FAIL), bytes([0xF0]),
 dptr(H_TICK), bytes([0xE0]), dptr(H_LAST), bytes([0xF0]),     # first poll one second later
 bytes([0x7F, 0x01, 0x22]),

 # ---- sec: replaces 'lcall 0x880F' at 0x9BB0 ----
 'sec',
 bytes([0x30, BIT_SEC]), R('sec1'),                            # jnb 0x21.0,sec1
 dptr(H_TICK), bytes([0xE0, 0x04, 0xF0]),
 'sec1',
 LJ(F_880F),

 # ---- fe_xfer: A = tx length, r7/r5/r3 = command/sub/x; tx XDATA TXB, 1 byte back into RXB -> r7 status ----
 'fe_xfer',
 bytes([0x75, 0x36, 0x00, 0xF5, 0x37,                          # tx length
        0x75, 0x38, 0x01, 0x75, 0x39, hi(TXB), 0x75, 0x3A, lo(TXB),   # tx pointer (xdata)
        0x75, 0x3B, 0x00, 0x75, 0x3C, 0x00, 0x75, 0x3D, 0x01,  # rx length 1
        0x75, 0x3E, 0x01, 0x75, 0x3F, hi(RXB), 0x75, 0x40, lo(RXB)]),  # rx pointer (xdata)
 bytes([0xE4]), dptr(RXB), bytes([0xF0]),
 LJ(F_64A4),

 # ---- q_link: A = front-end id -> A = 0 source active / 1 none / 0xFF no answer ----
 'q_link',
 dptr(TXB), bytes([0xF0]),
 bytes([0x7F, 0x60, 0x7D, 0xFF, 0x7B, 0x0B, 0x74, 0x01]), LC('fe_xfer'),
 bytes([0xBF, 0x10]), R('qf'),
 dptr(RXB), bytes([0xE0, 0x22]),
 'qf', bytes([0x74, 0xFF, 0x22]),

 # ---- rd_dec: A = 0x30/0x31/0x32 -> A = width high byte of MSA block 0x11xx6D (0 on failure) ----
 'rd_dec',
 bytes([0xFE]), dptr(TXB),
 bytes([0xE4, 0xF0, 0xA3, 0x74, 0x11, 0xF0, 0xA3, 0xEE, 0xF0, 0xA3, 0x74, 0x6D, 0xF0]),
 bytes([0x7F, 0xFF, 0x7D, 0xFF, 0x7B, 0x02, 0x74, 0x04]), LC('fe_xfer'),
 bytes([0xBF, 0x10]), R('rdf'),
 dptr(RXB), bytes([0xE0, 0x22]),
 'rdf', bytes([0xE4, 0x22]),

 # ---- lres: A = q_link answer, r5 = connector bit ----
 'lres',
 bytes([0xB4, 0xFF]), R('lr1'),
 xset(H_NF, 1), bytes([0x22]),
 'lr1',
 bytes([0x70]), R('lr2'),
 dptr(H_ACT), bytes([0xE0, 0x4D, 0xF0]),                       # H_ACT |= r5
 'lr2', bytes([0x22]),

 'pe', bytes([0x7F, 0x00, 0x22]),                              # poll: no event
 # ---- poll: replaces 'lcall 0x5BAA' at 0x9BB9 ----
 'poll',
 LC(F_5BAA),
 bytes([0xEF, 0x60, 0x01, 0x22]),                              # stock event (r7 != 0): return it as stock
 dptr(H_ON), bytes([0xE0, 0x60]), R('pe'),
 dptr(0x5E6A), bytes([0xE0, 0xB4, 0x01]), R('pe'),             # standby state only
 dptr(H_TICK), bytes([0xE0, 0xFE]),
 dptr(H_LAST), bytes([0xE0, 0x6E, 0x60]), R('pe'),             # same second: nothing to do
 bytes([0xEE, 0xF0]),                                          # H_LAST = H_TICK
 bytes([0xE4]), dptr(H_ACT), bytes([0xF0]), dptr(H_NF), bytes([0xF0]),
 bytes([0x74, 0x07]), LC('q_link'), bytes([0x7D, 0x01]), LC('lres'),
 bytes([0x74, 0x08]), LC('q_link'), bytes([0x7D, 0x02]), LC('lres'),
 dptr(H_NF), bytes([0xE0, 0x60]), R('nofail'),
 dptr(H_FAIL), bytes([0xE0, 0x04, 0xF0, 0xB4, 0x03]), R('p0'), # 3 rounds without answer -> release
 LJ('release'),
 'nofail',
 bytes([0xE4]), dptr(H_FAIL), bytes([0xF0]),
 dptr(H_MASK), bytes([0xE0, 0xF4, 0xFE]),                      # r6 = ~held
 dptr(0x5E81), bytes([0xE0, 0x60, 0x04, 0xEE, 0x54, 0xFE, 0xFE]),   # port 0 suppressed (fixed input): not a new source
 dptr(0x5E82), bytes([0xE0, 0x60, 0x04, 0xEE, 0x54, 0xFD, 0xFE]),   # port 1 likewise
 dptr(H_ACT), bytes([0xE0, 0x5E, 0x60]), R('nonew'),           # active and not held?
 bytes([0x30, 0xE0]), R('nb1'),                                # jnb acc.0,nb1
 bytes([0x7F, 0x00, 0x80]), R('wake'),
 'nb1', bytes([0x7F, 0x01, 0x80]), R('wake'),
 'nonew',
 bytes([0x74, 0x30]), LC('rd_dec'), bytes([0x70]), R('vid'),
 bytes([0x74, 0x31]), LC('rd_dec'), bytes([0x70]), R('vid'),
 bytes([0x74, 0x32]), LC('rd_dec'), bytes([0x70]), R('vid'),
 dptr(H_ACT), bytes([0xE0, 0x70, 0x03]), LJ('release'),        # no link left -> stock deep standby
 dptr(H_MASK), bytes([0xF0]),                                  # held = still active
 bytes([0x80]), R('p0'),
 'vid',
 dptr(H_MASK), bytes([0xE0]),
 bytes([0x7F, 0x00, 0xB4, 0x01]), R('v2'), bytes([0x80]), R('wake'),
 'v2', bytes([0x7F, 0x01, 0xB4, 0x02]), R('v3'), bytes([0x80]), R('wake'),
 'v3', bytes([0x7F, 0x05]),
 'wake',                                                       # r7 = port
 dptr(0x5E8A), bytes([0xEF, 0xF0]),
 xset(0x5E89, 9),
 bytes([0x75, 0x23, 0x01, 0x7F, 0x01, 0x22]),
 'p0', bytes([0x7F, 0x00, 0x22]),

 # ---- release: stock deep standby (front-end mode 3 with the saved mask) ----
 'release',
 bytes([0xE4]), dptr(H_ON), bytes([0xF0]),
 dptr(FLAG), bytes([0xE0, 0x54, 0x7F, 0xF0]),                  # no hold on a re-entry
 dptr(H_SAVE),
 bytes([0xE0, 0xF5, 0x28, 0xA3, 0xE0, 0xF5, 0x29, 0xA3, 0xE0, 0xF5, 0x2A, 0xA3, 0xE0, 0xF5, 0x2B]),
 bytes([0x7F, 0x03]), LC(F_8A25),
 bytes([0x7F, 0x00, 0x22]),
]

def assemble(prog, base):
    labels, a = {}, base
    for it in prog:
        if isinstance(it, str):
            assert it not in labels, 'duplicate label ' + it
            labels[it] = a
        elif isinstance(it, tuple): a += 1 if it[0] == 'rel' else 3
        else: a += len(it)
    out, a = bytearray(), base
    for it in prog:
        if isinstance(it, str): continue
        if isinstance(it, tuple) and it[0] == 'rel':
            off = labels[it[1]] - (a + 1)
            assert -128 <= off <= 127, it
            out.append(off & 0xFF); a += 1
        elif isinstance(it, tuple):
            t = labels[it[2]] if isinstance(it[2], str) else it[2]
            out += bytes([it[1], hi(t), lo(t)]); a += 3
        else:
            out += it; a += len(it)
    return bytes(out), labels

blob, L = assemble(prog, BASE)
assert BASE + len(blob) <= 0xA400, hex(BASE + len(blob))
assert cur(BASE, len(blob)) == b'\xff' * len(blob)
# other PM51 patches end below 0xA200
for f in ('pm51-input-filter.json', 'pm51-wake-window.json'):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'patches', f)
    if os.path.exists(p):
        for e in json.load(open(p))['edits']:
            a = int(e['addr'], 16)
            assert not (a < BASE + len(blob) and a + len(e['new']) // 2 > BASE), (f, e['addr'])

# stock code the patch relies on
for a, (old, _) in HOOKS.items():
    assert cur(a, 3).hex() == old, (hex(a), cur(a, 3).hex())
assert cur(0x4B0C, 14).hex() == '85262b85252a852429852328 7f03'.replace(' ', ''), cur(0x4B0C, 14).hex()   # mask -> 0x28..0x2B, r7 = 3
assert cur(0x8A25, 4).hex() == 'e4f52cf5'                     # front-end power mode
assert cur(0x8A6A, 7).hex() == '7d01ff1264a4bf', cur(0x8A6A, 7).hex()   # ... command 0x00 sub 1 via 0x64A4
assert cur(0x64A4, 6).hex() == '8f338d348b35'                  # frame: r7 cmd, r5 sub, r3 x
assert cur(0x98B6, 3).hex() == '8f2912'                        # register-style frame example (0xFF/0xFF)
assert cur(0x9BA5, 0x1B).hex() == '7f0112422f300603129296' '12880f' '129665' '12952c' '125baa' 'ef60eb22', cur(0x9BA5, 0x1B).hex()
assert cur(0x25E5, 2).hex() == 'd208'                          # timer ISR: setb 0x21.0 (once per second)
assert cur(0x887B, 2).hex() == 'c208'                          # 0x880F: clr 0x21.0
assert cur(0x539E, 6).hex() == '905e6ae06402'                  # state 0x5E6A (1 standby, 2 off)
assert cur(0x2AD5, 7).hex() == '9050007f007e30'                # startup clears XDATA 0x5000-0x7FFF
assert cur(0x5BAA, 8).hex() == 'e4f523905000' '74ff'           # classifier: 0x23 = 0, ...
assert cur(0x95D1, 3).hex() == '905e81'                        # suppress list 0x5E81+port (standby request)

hooks = {a: bytes([0x12, hi(L[lab]), lo(L[lab])]) for a, (_, lab) in HOOKS.items()}

def dis(code, base):
    return subprocess.run(['rasm2', '-a', '8051', '-o', hex(base), '-D', code.hex()],
                          capture_output=True, text=True).stdout.strip()
print(dis(blob, BASE))
print('labels', {k: hex(v) for k, v in L.items()})
for a, b in hooks.items():
    print('%04x  %s -> %s' % (a, cur(a, 3).hex(), b.hex()))

edits = [{'addr': '0x%04X' % BASE, 'old': 'ff' * len(blob), 'new': blob.hex(),
          'asm': 'bank-0 free space 0xA200: hold-link standby (pre, mode, sec, poll, release; front-end queries via 0x64A4)'}]
names = {0x4AF1: "standby entry: mov dptr,#0x5E97 -> lcall pre (hold off)",
         0x4B1A: "standby entry: lcall 0x8A25 (front-end mode 3) -> lcall mode (skipped while holding the link)",
         0x9BB0: "sleep loop: lcall 0x880F -> lcall sec (second counter)",
         0x9BB9: "sleep loop: lcall 0x5BAA -> lcall poll (classifier, then the hold poll)"}
for a, b in hooks.items():
    edits.append({'addr': '0x%04X' % a, 'old': cur(a, 3).hex(), 'new': b.hex(), 'asm': names[a]})

patch = {
 'name': 'pm51-hold-link',
 'summary': ('PM51: deep standby with the DP link kept (front-end stays in its normal mode) when the main firmware '
             'marks the standby request as link-held; the PM51 wakes on video (stream width) or a new link and drops '
             'to the stock deep standby when the link is released (Option A, ~4 W instead of 12.5 W)'),
 'status': 'untested',
 'space': 'pm51',
 'edits': edits,
 'notes': ("Addresses are PM51 code addresses (bank 0, package offset 0x10080 + addr). State in XDATA 0x7F00-0x7F10. "
           "Only acts when the standby block byte +3 (XDATA 0x5E95) has bit 7 set (gate-all-dp v5, which requires this "
           "patch); otherwise stock, so it is harmless alone. "
           "Generated by tools/patches_src_pm51_hold_link.py."),
}
out = os.environ.get('OUT', 'pm51-hold-link.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
