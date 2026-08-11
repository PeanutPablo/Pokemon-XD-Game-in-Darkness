"""Offline cross-reference scan for the vanilla-XD _MsgID SDA object.

Reads the verified main.elf and symbols.txt only.  It does not connect to
Dolphin and cannot write game memory.
"""

from __future__ import annotations

import bisect
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


TARGET = 0x804EB284
SDA_BASE = 0x804EFE20
DISP = (TARGET - SDA_BASE) & 0xFFFF  # 0xB464 / -19356


@dataclass(order=True)
class Symbol:
    address: int
    name: str
    size: int
    section: str
    kind: str


def load_symbols(path: Path) -> tuple[list[Symbol], dict[int, Symbol]]:
    pattern = re.compile(
        r"^(.+?) = \.(\w+):0x([0-9A-Fa-f]+);"
        r".*?type:(\w+).*?size:0x([0-9A-Fa-f]+)"
    )
    symbols: list[Symbol] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            name, section, address, kind, size = match.groups()
            symbols.append(
                Symbol(int(address, 16), name, int(size, 16), section, kind)
            )
    symbols.sort()
    return symbols, {symbol.address: symbol for symbol in symbols}


class ElfReader:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        e_phoff = struct.unpack_from(">I", self.data, 0x1C)[0]
        e_phentsize = struct.unpack_from(">H", self.data, 0x2A)[0]
        e_phnum = struct.unpack_from(">H", self.data, 0x2C)[0]
        self.segments: list[tuple[int, int, int, int]] = []
        for index in range(e_phnum):
            offset = e_phoff + index * e_phentsize
            (
                p_type,
                p_offset,
                p_vaddr,
                _p_paddr,
                p_filesz,
                p_memsz,
                p_flags,
                _p_align,
            ) = struct.unpack_from(">8I", self.data, offset)
            if p_type == 1:
                self.segments.append((p_vaddr, p_offset, p_filesz, p_flags))

    def executable_words(self):
        for vaddr, file_offset, file_size, flags in self.segments:
            if not flags & 1:
                continue
            data = self.data[file_offset : file_offset + file_size]
            for offset in range(0, len(data) - 3, 4):
                yield vaddr + offset, int.from_bytes(data[offset : offset + 4], "big")


def containing_function(symbols: list[Symbol], addresses: list[int], address: int):
    index = bisect.bisect_right(addresses, address) - 1
    while index >= 0:
        symbol = symbols[index]
        if (
            symbol.kind == "function"
            and symbol.section == "text"
            and symbol.address <= address < symbol.address + symbol.size
        ):
            return symbol
        index -= 1
    return None


def branch_target(word: int, address: int) -> int | None:
    if (word >> 26) != 18 or not (word & 1):
        return None
    displacement = word & 0x03FFFFFC
    if displacement & 0x02000000:
        displacement -= 0x04000000
    return displacement if word & 2 else (address + displacement) & 0xFFFFFFFF


def describe_direct(word: int) -> str | None:
    op = word >> 26
    reg = (word >> 21) & 31
    base = (word >> 16) & 31
    displacement = word & 0xFFFF
    if base != 13 or displacement != DISP:
        return None
    names = {
        14: "addi/address",
        32: "lwz/read-u32",
        33: "lwzu/read-u32-update",
        34: "lbz/read-u8",
        35: "lbzu/read-u8-update",
        40: "lhz/read-u16",
        41: "lhzu/read-u16-update",
        42: "lha/read-s16",
        43: "lhau/read-s16-update",
        36: "stw/write-u32",
        37: "stwu/write-u32-update",
        38: "stb/write-u8",
        39: "stbu/write-u8-update",
        44: "sth/write-u16",
        45: "sthu/write-u16-update",
        48: "lfs/read-f32",
        50: "lfd/read-f64",
        52: "stfs/write-f32",
        54: "stfd/write-f64",
    }
    name = names.get(op)
    return f"{name} r{reg}" if name else f"op{op} r{reg}"


def main() -> int:
    elf_path = Path(sys.argv[1])
    symbol_path = Path(sys.argv[2])
    symbols, exact = load_symbols(symbol_path)
    addresses = [symbol.address for symbol in symbols]
    reader = ElfReader(elf_path)

    direct = []
    callers = []
    getter = exact[0x801547AC]
    for address, word in reader.executable_words():
        description = describe_direct(word)
        if description:
            direct.append((address, word, description))
        if branch_target(word, address) == getter.address:
            callers.append((address, word))

    print(
        f"_MsgID=0x{TARGET:08X} SDA_BASE=0x{SDA_BASE:08X} "
        f"displacement=0x{DISP:04X} ({TARGET-SDA_BASE})"
    )
    print("\nDIRECT SDA REFERENCES")
    for address, word, description in direct:
        owner = containing_function(symbols, addresses, address)
        owner_text = (
            f"{owner.name}+0x{address-owner.address:X}" if owner else "<unresolved>"
        )
        print(f"0x{address:08X}: {word:08X} {description:24} {owner_text}")

    print("\nDIRECT CALLERS OF msgctrlMsgID")
    for address, word in callers:
        owner = containing_function(symbols, addresses, address)
        owner_text = (
            f"{owner.name}+0x{address-owner.address:X}" if owner else "<unresolved>"
        )
        print(f"0x{address:08X}: {word:08X} {owner_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
