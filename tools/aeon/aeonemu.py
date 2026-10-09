#!/usr/bin/env python3
"""Small AEON R2 instruction-set emulator for checking runtime patches without hardware.

Covers the integer subset the OSD code uses (loads/stores, ALU, compares, flag and
compare-and-branch forms, calls). Data memory is little-endian; the runtime image
is mapped at its link address 0x200000 together with RAM up to 0x500000.

Register access (RIU) is not emulated at the bus level: the firmware's accessors
are replaced by Python stubs (byte write 0x23D9E7, byte read 0x23D972, masked
write 0x23DC0F, 16-bit read 0x23DBB3; the delay helpers 0x241708 and 0x20E375
and the vertical-blank wait 0x23F9EE return at once). Writes to the OSD bank go to a model of the OSD engine (OSD
class): mode register 0x101C68, data port 0x101C66/0x101C67, font RAM as an
18-bit-word bit stream, tile code/attribute RAM and the 256-entry palette, as
described in docs/firmware-map.md section 56. The model reflects what was
measured on hardware; it is not a verified copy of the hardware.

    from aeonemu import CPU
    cpu = CPU(image_bytes)
    cpu.call(0x253991)              # runs until the function returns
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aeondis as A

M32 = 0xFFFFFFFF
RET_MAGIC = 0xDEAD0000


def s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


class Stop(Exception):
    pass


class OSD:
    """OSD register bank model (0x101C00-0x101DFF)."""

    def __init__(self):
        self.regs = {}
        self.mode = 0
        self.addr = 0
        self.codehi = 0
        self.font = bytearray(0x4000 * 18 // 8)      # 0x4000 words of 18 bits as one bit stream
        self.fptr = 0                                 # byte position in `font` (address words x 18 / 8)
        self.fontw = 0                                # font data bytes written
        self.code = {}                                # tile word -> code (12 bit)
        self.attr = {}                                # tile word -> attribute
        self.pal = [[0, 0, 0] for _ in range(256)]   # bytes in the order written
        self.pidx = 0
        self.pbyte = 0

    def write(self, reg, val):
        val &= 0xFF
        if reg == 0x101C68:
            self.mode = val & 0x1F
        elif reg == 0x101C66:
            m = self.mode
            if m == 0:
                self.addr = (self.addr & 0xFF00) | val
                self.fptr = self.addr * 18 // 8        # font data pointer (auto-increments in mode 3)
            elif m == 3:
                self.font[self.fptr] = val
                self.fptr += 1
                self.fontw += 1
            elif m == 1:
                self.code[self.addr] = (self.codehi << 8) | val
                self.addr += 1
            elif m == 2:
                self.attr[self.addr] = val
                self.addr += 1
            elif m == 0x0A:
                self.pidx, self.pbyte = val, 0
            elif m == 0x0D:
                self.pal[self.pidx][self.pbyte] = val
                self.pbyte += 1
                if self.pbyte == 3:
                    self.pbyte, self.pidx = 0, (self.pidx + 1) & 0xFF
        elif reg == 0x101C67:
            if self.mode == 0:
                self.addr = (self.addr & 0xFF) | (val << 8)
                self.fptr = self.addr * 18 // 8
            elif self.mode == 1:
                self.codehi = val & 0xF
        self.regs[reg] = val

    def read(self, reg):
        if reg == 0x101C67 and self.mode == 1:
            return self.codehi
        return self.regs.get(reg, 0)

    def glyph(self, code, bpp):
        """Pixel rows (18 x 12 values) of the glyph stored for `code` (RAM word 0x880 + 12 x code)."""
        b0 = (0x880 + 12 * code) * 18
        bit = lambda n: (self.font[n >> 3] >> (7 - (n & 7))) & 1
        rows = []
        for y in range(18):
            row = []
            for x in range(12):
                n = b0 + (y * 12 + x) * bpp
                v = 0
                for k in range(bpp):
                    v = (v << 1) | bit(n + k)
                row.append(v)
            rows.append(row)
        return rows


class CPU:
    def __init__(self, image, base=0x200000, size=0x300000):
        self.base = base
        self.mem = bytearray(size)
        self.mem[:len(image)] = image
        self.r = [0] * 32
        self.f = False
        self.pc = 0
        self.osd = OSD()
        self.stubs = {}
        self.steps = 0
        self.trace = False
        self._install_riu()

    # ---- memory
    def _off(self, a, n):
        o = a - self.base
        if not (0 <= o and o + n <= len(self.mem)):
            raise Stop('memory access %#x at pc %#x' % (a, self.pc))
        return o

    def lb(self, a): return self.mem[self._off(a, 1)]
    def lh(self, a): o = self._off(a, 2); return self.mem[o] | self.mem[o + 1] << 8
    def lw(self, a): o = self._off(a, 4); return int.from_bytes(self.mem[o:o + 4], 'little')
    def sb(self, a, v): self.mem[self._off(a, 1)] = v & 0xFF
    def sh(self, a, v): o = self._off(a, 2); self.mem[o:o + 2] = (v & 0xFFFF).to_bytes(2, 'little')
    def sw(self, a, v): o = self._off(a, 4); self.mem[o:o + 4] = (v & M32).to_bytes(4, 'little')

    # ---- register accessors
    def _install_riu(self):
        def ret(c): c.pc = c.r[9]
        def wr(c): c.osd.write(c.r[3], c.r[4]); ret(c)
        def rd(c): c.r[3] = c.osd.read(c.r[3]); ret(c)
        def wmask(c):
            reg, v, m = c.r[3], c.r[4], c.r[5]
            c.osd.write(reg, (c.osd.read(reg) & ~m) | (v & m)); ret(c)
        def rd16(c): c.r[3] = c.osd.read(c.r[3]) | c.osd.read(c.r[3] + 1) << 8; ret(c)
        self.stubs.update({0x23D9E7: wr, 0x23D972: rd, 0x23DC0F: wmask, 0x23DBB3: rd16,
                           0x241708: ret, 0x20E375: ret,
                           0x23F9EE: ret})   # OSD off + wait for vertical blank (0x101CD3 bit 7, ISR timeout)

    # ---- execution
    def call(self, addr, *args, sp=0x4F0000, limit=20_000_000):
        """Call `addr` with r3.. = args; returns r3 when the function returns."""
        for k, v in enumerate(args):
            self.r[3 + k] = v & M32
        self.r[1] = sp
        self.r[9] = RET_MAGIC
        self.pc = addr
        n = 0
        while self.pc != RET_MAGIC:
            self.step()
            n += 1
            if n > limit:
                raise Stop('step limit at %#x' % self.pc)
        return self.r[3]

    def step(self):
        pc = self.pc
        if pc in self.stubs:
            self.stubs[pc](self)
            return
        x = A.decode(self.mem, self._off(pc, 1), pc)
        if x is None or x['name'] is None:
            raise Stop('invalid instruction at %#x' % pc)
        if self.trace:
            print('%08x %-10s %s' % (pc, x['mnem'], x['ops']))
        self.steps += 1
        self.pc = pc + x['len']
        self._exec(x, pc, self.pc)
        self.r[0] = 0

    def _exec(self, x, pc, nxt):
        n, v, r = x['name'], x['vals'], self.r
        R = lambda ch: r[v[ch][1]]
        def setd(ch, val): r[v[ch][1]] = val & M32
        op = n.split('.', 1)[1]
        imm = next((v[ch][1] for ch in ('I', 'O', 'Y', 'N', 't', 'H', 'U', '$', '%') if ch in v and v[ch][0] != 'reg'), None)
        tgt = x['target']
        if op == 'movi': setd('D', imm)
        elif op == 'addi': setd('D', (r[v['D'][1]] if n == 'bt.addi' else R('A')) + imm)
        elif op == 'mov': setd('D', R('A'))
        elif op == 'movhi': setd('D', imm << 16)
        elif op == 'ori': setd('D', R('A') | (imm & 0xFFFF))
        elif op == 'andi': setd('D', R('A') & (imm & 0xFFFF))
        elif op == 'xori': setd('D', R('A') ^ (imm & M32))
        elif op == 'muli': setd('D', s32(R('A')) * imm)
        elif op in ('add', 'sub', 'and', 'or', 'xor', 'nand', 'andn', 'mul', 'mulu', 'div', 'divu', 'sll', 'srl', 'sra'):
            a, b = (R('A'), R('B')) if 'B' in v else (r[v['D'][1]], R('A'))
            res = {'add': lambda: a + b, 'sub': lambda: a - b, 'and': lambda: a & b, 'or': lambda: a | b,
                   'xor': lambda: a ^ b, 'nand': lambda: ~(a & b), 'andn': lambda: a & ~b, 'mul': lambda: s32(a) * s32(b), 'mulu': lambda: a * b,
                   'div': lambda: int(s32(a) / s32(b)) if b else 0, 'divu': lambda: a // b if b else 0,
                   'sll': lambda: a << (b & 31), 'srl': lambda: a >> (b & 31), 'sra': lambda: s32(a) >> (b & 31)}[op]()
            setd('D', res)
        elif op in ('slli', 'srli', 'srai'):
            a, h = R('A'), imm & 31
            setd('D', a << h if op == 'slli' else a >> h if op == 'srli' else s32(a) >> h)
        elif op == 'extbz': setd('D', R('A') & 0xFF)
        elif op == 'extbs': setd('D', ((R('A') & 0xFF) ^ 0x80) - 0x80)
        elif op == 'exthz': setd('D', R('A') & 0xFFFF)
        elif op == 'exths': setd('D', ((R('A') & 0xFFFF) ^ 0x8000) - 0x8000)
        elif op == 'ff1': a = R('A'); setd('D', (a & -a).bit_length() if a else 0)
        elif op == 'fl1': setd('D', R('A').bit_length())
        elif op == 'cmov': setd('D', R('A') if self.f else R('B'))
        elif op == 'cmovri': setd('D', R('A') if self.f else v['I'][1])
        elif op == 'cmovir': setd('D', v['I'][1] if self.f else R('B'))
        elif op == 'cmovii': setd('D', v['I'][1] if self.f else v['L'][1])
        elif op.startswith('sf'):
            c = op[2:]
            if c.endswith('i'):
                self.f = self._cmp(c[:-1], R('A'), imm & M32)
            else:
                self.f = self._cmp(c, R('A'), R('B'))
        elif op in ('bf', 'bnf'):
            if self.f == (op == 'bf'):
                self.pc = tgt
        elif op in ('beqi', 'bnei', 'blesi', 'bgtsi', 'bleui', 'bgtui'):
            if self._cmp(op[1:-1], R('A'), imm & M32):
                self.pc = tgt
        elif op in ('beq', 'bne', 'bles', 'bleu', 'bgts', 'bgtu'):
            if self._cmp(op[1:], R('A'), R('B')):
                self.pc = tgt
        elif op == 'j': self.pc = tgt
        elif op == 'jal': r[9] = nxt; self.pc = tgt
        elif op == 'jr': self.pc = R('A')
        elif op == 'jalr': t = R('A'); r[9] = nxt; self.pc = t
        elif op in ('lbz', 'lbs', 'lhz', 'lhs', 'lwz'):
            d = '?' if '?' in v else 'D'
            off = next(v[ch][1] for ch in v if ch not in (d, 'A'))
            a = (R('A') + off) & M32
            val = {'lbz': lambda: self.lb(a), 'lbs': lambda: (self.lb(a) ^ 0x80) - 0x80, 'lhz': lambda: self.lh(a),
                   'lhs': lambda: (self.lh(a) ^ 0x8000) - 0x8000, 'lwz': lambda: self.lw(a)}[op]()
            setd(d, val)
        elif op in ('sb', 'sh', 'sw'):
            off = next(v[ch][1] for ch in v if ch not in ('A', 'B'))
            {'sb': self.sb, 'sh': self.sh, 'sw': self.sw}[op]((R('A') + off) & M32, R('B'))
        elif op == 'nop':
            pass
        else:
            raise Stop('not emulated: %s at %#x' % (n, pc))

    @staticmethod
    def _cmp(c, a, b):
        sa, sb = s32(a), s32(b)
        return {'eq': a == b, 'ne': a != b, 'gts': sa > sb, 'les': sa <= sb, 'gtu': a > b, 'leu': a <= b}[c]
