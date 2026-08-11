"""
Minimal but broader-coverage PowerPC disassembler for statically reading
xd-decomp's verified build/GXXE01/main.elf, extending the store-only
decoder used for the watchpoint investigation. Not a complete PPC
disassembler -- covers the common instruction classes needed to read
compiler-generated function bodies (loads, stores, branches, compares,
basic arithmetic/logical, mfspr/mtspr for lr/ctr).

Read-only: parses the ELF file on disk, no live connection, no writes.
"""
import struct
import sys
import os

REG = lambda n: f"r{n}"


def sext16(v):
    return v - 0x10000 if v >= 0x8000 else v


def decode(word: int, addr: int) -> str:
    op = (word >> 26) & 0x3F
    rD = (word >> 21) & 0x1F
    rS = rD
    rA = (word >> 16) & 0x1F
    rB = (word >> 11) & 0x1F
    d = word & 0xFFFF
    sd = sext16(d)

    if word == 0x4E800020:
        return "blr"
    if word == 0x4E800021:
        return "blrl"

    if op == 18:  # b / bl
        li = word & 0x03FFFFFC
        if li & 0x02000000:
            li -= 0x04000000
        aa = word & 2
        lk = word & 1
        target = li if aa else (addr + li) & 0xFFFFFFFF
        return f"{'bl' if lk else 'b'} 0x{target:08X}"

    if op == 16:  # bc / bcl
        bo = (word >> 21) & 0x1F
        bi = (word >> 16) & 0x1F
        bd = word & 0xFFFC
        if bd & 0x8000:
            bd -= 0x10000
        aa = word & 2
        lk = word & 1
        target = bd if aa else (addr + bd) & 0xFFFFFFFF
        return f"{'bcl' if lk else 'bc'} {bo},{bi},0x{target:08X}"

    if op == 19:
        xo = (word >> 1) & 0x3FF
        lk = word & 1
        bo = (word >> 21) & 0x1F
        bi = (word >> 16) & 0x1F
        if xo == 16:
            return f"{'bclrl' if lk else 'bclr'} {bo},{bi}"
        if xo == 528:
            return f"{'bcctrl' if lk else 'bcctr'} {bo},{bi}"
        if xo == 0:
            return f"mcrf cr{rD>>2},cr{rA>>2}"
        return f".long 0x{word:08X}  (XL-form op19 xo={xo})"

    if op == 11:
        return f"cmpi cr{rD>>2},{REG(rA)},{sd}"
    if op == 10:
        return f"cmpli cr{rD>>2},{REG(rA)},{d}"

    if op == 12:
        return f"addic {REG(rD)},{REG(rA)},{sd}"
    if op == 13:
        return f"addic. {REG(rD)},{REG(rA)},{sd}"
    if op == 14:
        if rA == 0:
            return f"li {REG(rD)},{sd}"
        return f"addi {REG(rD)},{REG(rA)},{sd}"
    if op == 15:
        if rA == 0:
            return f"lis {REG(rD)},{d}"
        return f"addis {REG(rD)},{REG(rA)},{d}"

    if op == 20:
        sh = (word >> 11) & 0x1F
        mb = (word >> 6) & 0x1F
        me = (word >> 1) & 0x1F
        return f"rlwimi {REG(rA)},{REG(rS)},{sh},{mb},{me}"
    if op == 21:
        sh = (word >> 11) & 0x1F
        mb = (word >> 6) & 0x1F
        me = (word >> 1) & 0x1F
        return f"rlwinm {REG(rA)},{REG(rS)},{sh},{mb},{me}"

    if op == 24:
        return f"ori {REG(rA)},{REG(rS)},0x{d:04X}" if not (rA == 0 and rS == 0 and d == 0) else "nop"
    if op == 25:
        return f"oris {REG(rA)},{REG(rS)},0x{d:04X}"
    if op == 26:
        return f"xori {REG(rA)},{REG(rS)},0x{d:04X}"
    if op == 27:
        return f"xoris {REG(rA)},{REG(rS)},0x{d:04X}"
    if op == 28:
        return f"andi. {REG(rA)},{REG(rS)},0x{d:04X}"
    if op == 29:
        return f"andis. {REG(rA)},{REG(rS)},0x{d:04X}"

    D_LOADS = {32: "lwz", 33: "lwzu", 34: "lbz", 35: "lbzu", 40: "lhz", 41: "lhzu", 42: "lha", 43: "lhau"}
    if op in D_LOADS:
        return f"{D_LOADS[op]} {REG(rD)},{sd}({REG(rA)})"
    D_STORES = {36: "stw", 37: "stwu", 38: "stb", 39: "stbu", 44: "sth", 45: "sthu"}
    if op in D_STORES:
        return f"{D_STORES[op]} {REG(rS)},{sd}({REG(rA)})"
    if op == 46:
        return f"lmw {REG(rD)},{sd}({REG(rA)})"
    if op == 47:
        return f"stmw {REG(rS)},{sd}({REG(rA)})"
    if op == 48:
        return f"lfs f{rD},{sd}({REG(rA)})"
    if op == 50:
        return f"lfd f{rD},{sd}({REG(rA)})"
    if op == 52:
        return f"stfs f{rS},{sd}({REG(rA)})"
    if op == 54:
        return f"stfd f{rS},{sd}({REG(rA)})"

    if op == 31:
        xo = (word >> 1) & 0x3FF
        X_ARITH = {266: "add", 40: "subf", 28: "and", 444: "or", 316: "xor", 124: "nor", 8: "subfc"}
        if xo in X_ARITH:
            return f"{X_ARITH[xo]} {REG(rA)},{REG(rS)},{REG(rB)}"
        if xo == 0:
            return f"cmp cr{rD>>2},{REG(rA)},{REG(rB)}"
        if xo == 32:
            return f"cmpl cr{rD>>2},{REG(rA)},{REG(rB)}"
        if xo == 339:
            spr = ((word >> 16) & 0x1F) | (((word >> 11) & 0x1F) << 5)
            name = {8: "LR", 9: "CTR"}.get(spr, f"spr{spr}")
            return f"mfspr {REG(rD)},{name}"
        if xo == 467:
            spr = ((word >> 16) & 0x1F) | (((word >> 11) & 0x1F) << 5)
            name = {8: "LR", 9: "CTR"}.get(spr, f"spr{spr}")
            return f"mtspr {name},{REG(rS)}"
        if xo == 954:
            return f"extsb {REG(rA)},{REG(rS)}"
        if xo == 922:
            return f"extsh {REG(rA)},{REG(rS)}"
        X_LOADS = {23: "lwzx", 87: "lbzx", 279: "lhzx", 343: "lhax"}
        if xo in X_LOADS:
            return f"{X_LOADS[xo]} {REG(rD)},{REG(rA)},{REG(rB)}"
        X_STORES = {151: "stwx", 215: "stbx", 407: "sthx", 183: "stwux", 247: "stbux", 439: "sthux"}
        if xo in X_STORES:
            return f"{X_STORES[xo]} {REG(rS)},{REG(rA)},{REG(rB)}"
        return f".long 0x{word:08X}  (X-form op31 xo={xo})"

    return f".long 0x{word:08X}  (op{op})"


class ElfReader:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        e_phoff = struct.unpack_from(">I", self.data, 0x1C)[0]
        e_phentsize = struct.unpack_from(">H", self.data, 0x2A)[0]
        e_phnum = struct.unpack_from(">H", self.data, 0x2C)[0]
        self.segments = []
        for i in range(e_phnum):
            off = e_phoff + i * e_phentsize
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from(">8I", self.data, off)
            if p_type == 1:
                self.segments.append((p_vaddr, p_offset, p_filesz))

    def read(self, vaddr, length):
        for seg_vaddr, seg_off, seg_filesz in self.segments:
            if seg_vaddr <= vaddr < seg_vaddr + seg_filesz:
                file_off = seg_off + (vaddr - seg_vaddr)
                return self.data[file_off:file_off + length]
        return None


def main():
    elf_path = sys.argv[1]
    addr = int(sys.argv[2], 16)
    size = int(sys.argv[3], 16)
    reader = ElfReader(elf_path)
    raw = reader.read(addr, size)
    if raw is None:
        print(f"Address 0x{addr:08X} not found in any PT_LOAD segment.")
        return 1
    for i in range(0, len(raw), 4):
        a = addr + i
        word = int.from_bytes(raw[i:i+4], "big")
        print(f"0x{a:08X}: {word:08X}  {decode(word, a)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
