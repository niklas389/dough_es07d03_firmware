#!/usr/bin/env bash
# widthdump.sh - read the values that decide the DP input width (half-width
# picture, docs/firmware-map.md section 50) on a diag-poke build, then decode them.
#
#   MON=1 SPECCTL=./specctl tools/widthdump.sh > width_ok.txt      (correct picture)
#   MON=1 SPECCTL=./specctl tools/widthdump.sh > width_fault.txt   (with the fault on screen)
#
# Read-only (plain RAM loads through diag-poke; needs the diag-poke version with
# the window / DP receiver / path record pages). About 230 reads, 1-2 minutes.
# Path 0 "+0x94 01, +0x98 03" = the two links are paired (4K 144 Hz, section 57/58).
# The raw "addr value" lines are printed first, the decoded summary after them.
set -u
here=$(dirname "$0")
raw=$(mktemp)
trap 'rm -f "$raw"' EXIT

ranges=(
  0x453C70-0x453C73                          # flags (bit 13: DP link-event pause)
  0x48252A-0x48252F                          # settings +0x5A..+0x5F (path index, window map)
  0x482529-0x482529                          # settings +0x59 (layout: 0 = single window)
  0x2024A0-0x2024A5                          # pair-replay: last front-end routing report, valid, replays
)
for w in 0 1; do                             # window records 0x3B4950 + 0xB0*w
  b=$(( 0x3B4950 + 0xB0 * w ))
  ranges+=( $(printf '0x%X-0x%X 0x%X-0x%X 0x%X-0x%X 0x%X-0x%X 0x%X-0x%X 0x%X-0x%X' \
    $b $((b+3)) $((b+0xC)) $((b+0xC)) $((b+0x1C)) $((b+0x20)) $((b+0x4C)) $((b+0x5B)) \
    $((b+0x70)) $((b+0x70)) $((b+0x80)) $((b+0x8A))) )
done
for r in 0 1 2; do                           # scaler DP receiver records 0x47F7D8 + 0x74*r
  b=$(( 0x47F7D8 + 0x74 * r ))
  ranges+=( $(printf '0x%X-0x%X 0x%X-0x%X 0x%X-0x%X 0x%X-0x%X' \
    $((b+0x11)) $((b+0x11)) $((b+0x36)) $((b+0x3A)) $((b+0x5C)) $((b+0x5D)) $((b+0x68)) $((b+0x68))) )
  t=$(( 0x47F934 + 0x30 * r ))               # timing records 0x47F934 + 0x30*r
  ranges+=( $(printf '0x%X-0x%X' $((t+2)) $((t+0x15))) )
done
for p in 0 1; do                             # input path records 0x4821AC + 0xA8*p
  b=$(( 0x4821AC + 0xA8 * p ))
  ranges+=( $(printf '0x%X-0x%X 0x%X-0x%X 0x%X-0x%X 0x%X-0x%X 0x%X-0x%X' \
    $b $b $((b+0xC)) $((b+0xF)) $((b+0x18)) $((b+0x29)) $((b+0x94)) $((b+0x94)) $((b+0x98)) $((b+0x98))) )
done

"$here/regdump.sh" "${ranges[@]}" | tee "$raw"
echo
python3 - "$raw" <<'EOF'
import sys
v = {}
for line in open(sys.argv[1]):
    a, x = line.split()
    v[int(a, 16)] = int(x, 16) if x.startswith('0x') else None
def b(a):
    x = v.get(a)
    return '--' if x is None else '%02X' % x
def h(a):                                     # little-endian 16-bit
    lo, hi = v.get(a), v.get(a + 1)
    return None if lo is None or hi is None else lo | hi << 8
def hs(a):
    x = h(a)
    return '----' if x is None else '%5d' % x
def bit(a, n):
    x = v.get(a)
    return '-' if x is None else str((x >> n) & 1)

print('0x453C70 bit 13 (DP link-event pause): %s   settings +0x5A..+0x5F: %s' %
      (bit(0x453C71, 5), ' '.join(b(0x48252A + i) for i in range(6))))
print('layout settings +0x59: %s   pair-replay: last routing report %s %s %s (valid %s)  replays %s  replayed since last paired %s' %
      (b(0x482529), b(0x2024A0), b(0x2024A1), b(0x2024A2), b(0x2024A3), b(0x2024A4), b(0x2024A5)))
for w in (0, 1):
    B = 0x3B4950 + 0xB0 * w
    print('window %d: source %s  state %s  flags +0x1C %s  status +0x20 %s  +0x70 %s  +0x80 %s  '
          'doubling +0x88 %s  +0x89 %s  +0x8A %s' %
          (w, ''.join(b(B + 3 - i) for i in range(4)), b(B + 0xC), b(B + 0x1C), b(B + 0x20), b(B + 0x70),
           b(B + 0x80), b(B + 0x88), b(B + 0x89), b(B + 0x8A)))
    print('          rect path 0: x %s y %s w %s h %s   rect path 1: x %s y %s w %s h %s' %
          tuple(hs(B + 0x4C + 2 * i) for i in range(8)))
fmt = {0: 'RGB', 1: 'YCbCr 4:4:4', 2: 'YCbCr 4:2:2', 3: 'YCbCr 4:2:0', 4: 'Y only', 5: 'RAW'}
for r in (0, 1, 2):
    B = 0x47F7D8 + 0x74 * r
    T = 0x47F934 + 0x30 * r
    f = v.get(B + 0x36)
    print('DP rx %d: state +0x11 %s  colour format +0x36 %s (%s)  +0x37 %s  +0x38 %s  +0x39 %s  +0x3A %s  '
          'MISC0 %s  MISC1 %s (VSC SDP %s)  +0x68 %s' %
          (r, b(B + 0x11), b(B + 0x36), fmt.get(f, '?'), b(B + 0x37), b(B + 0x38), b(B + 0x39), b(B + 0x3A),
           b(B + 0x5C), b(B + 0x5D), bit(B + 0x5D, 6), b(B + 0x68)))
    print('         timing +0x02..+0x14: %s' % ' '.join(hs(T + 2 + 2 * i) for i in range(10)))
for p in (0, 1):
    B = 0x4821AC + 0xA8 * p
    print('path %d: active %s  width %s  height %s (OSD shows these)  port +0x28 %s  +0x94 %s  +0x98 %s' %
          (p, b(B), hs(B + 0xC), hs(B + 0xE), b(B + 0x28), b(B + 0x94), b(B + 0x98)))
    print('        measured +0x18..+0x26: %s' % ' '.join(hs(B + 0x18 + 2 * i) for i in range(8)))
EOF
