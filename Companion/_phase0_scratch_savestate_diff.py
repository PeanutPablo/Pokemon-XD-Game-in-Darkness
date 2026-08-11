"""
Offline, read-only parser/differ for Dolphin save states (.sav files the
user made manually via the in-game save-state hotkeys), used to
cross-check and extend the live GDB watchpoint investigation into the
battle command menu's live selection-tracking field.

This does NOT touch the live emulator at all -- it only reads static files
from disk (the .sav files and the built main.elf), matching the same
read-only spirit as the GDB RSP allowlist used elsewhere in Phase 0C.

Dolphin on-disk save-state format (from Source/Core/Core/State.h/.cpp,
STATE_VERSION=192, fetched from dolphin-emu/dolphin upstream for this):

  StateHeaderLegacy   (24 bytes, host-native/little-endian ints)
    char game_id[6]; char reserved1[2]; u32 lzo_size (0 for new format);
    char reserved2[4]; double time;
  StateHeaderVersion  (8 bytes)
    u32 version_cookie; u32 version_string_length;
  <version_string, version_string_length bytes>
  StateExtendedBaseHeader (16 bytes)
    u16 header_version; u16 compression_type (0=Uncompressed, 1=LZ4);
    u32 payload_offset; u64 uncompressed_size;
  <payload, starting payload_offset bytes after the extended header>
    LZ4 (if compression_type==1): sequence of chunks, each
      s32 compressed_len (little-endian) + that many compressed bytes,
      until decompressed total == uncompressed_size.

The decompressed payload is Dolphin's PointerWrap-serialized full machine
state (Wii flag, MEM1/MEM2 sizes, Movie, video backend string, CoreTiming,
HW::DoState [Memory, VI, PI, DSP, DVD, GPFifo, CPU, PE, CP, PatchEngine,
EXI, SI, AI, ...], PowerPC, Wiimote, Gecko, achievements). Rather than
reimplementing that entire serialization order just to find where the
MEM1 (24MB GameCube RAM) array begins, this script locates it by ANCHOR
SEARCH: it extracts a long, distinctive byte run of known static code
from the verified build's main.elf (code is not self-modifying at
runtime) and searches for those exact bytes in the decompressed buffer.
Two independent anchors are used and cross-checked to guard against a
coincidental match.
"""
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import lz4.block  # noqa: E402

ELF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "xd-decomp", "build", "GXXE01", "main.elf"
)

# Two anchors, chosen from known-static SDK/game code far apart in the
# address space, each a long run so a coincidental match is implausible.
ANCHOR_1_ADDR = 0x800BB348  # PADRead
ANCHOR_2_ADDR = 0x8001D088  # menuFightMainCtrl
ANCHOR_LEN = 512

MEM1_BASE_VADDR = 0x80000000
MEM1_SIZE = 0x01800000  # 24 MiB


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
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
                struct.unpack_from(">8I", self.data, off)
            if p_type == 1:
                self.segments.append((p_vaddr, p_offset, p_filesz))

    def read(self, vaddr, length):
        for seg_vaddr, seg_off, seg_filesz in self.segments:
            if seg_vaddr <= vaddr < seg_vaddr + seg_filesz:
                file_off = seg_off + (vaddr - seg_vaddr)
                return self.data[file_off:file_off + length]
        return None


def parse_and_decompress(path):
    with open(path, "rb") as f:
        data = f.read()

    legacy_lzo_size = struct.unpack_from("<I", data, 8)[0]
    if legacy_lzo_size != 0:
        raise RuntimeError(f"{path}: legacy LZO-format state not supported by this script")

    version_cookie, version_string_length = struct.unpack_from("<II", data, 24)
    pos = 32 + version_string_length

    header_version, compression_type, payload_offset, uncompressed_size = \
        struct.unpack_from("<HHIQ", data, pos)
    pos += 16
    pos += payload_offset

    if compression_type == 0:
        payload = data[pos:pos + uncompressed_size]
        return payload

    if compression_type != 1:
        raise RuntimeError(f"{path}: unknown compression_type {compression_type}")

    out = bytearray()
    total = 0
    while total < uncompressed_size:
        (clen,) = struct.unpack_from("<i", data, pos)
        pos += 4
        chunk = data[pos:pos + clen]
        pos += clen
        remaining = uncompressed_size - total
        dec = lz4.block.decompress(chunk, uncompressed_size=remaining)
        out += dec
        total += len(dec)
    return bytes(out)


def find_mem1_base(decompressed, elf):
    anchor1 = elf.read(ANCHOR_1_ADDR, ANCHOR_LEN)
    anchor2 = elf.read(ANCHOR_2_ADDR, ANCHOR_LEN)
    if anchor1 is None or anchor2 is None:
        raise RuntimeError("Could not read anchor bytes from ELF")

    idx1 = decompressed.find(anchor1)
    if idx1 == -1 or decompressed.find(anchor1, idx1 + 1) != -1:
        raise RuntimeError("Anchor 1 (PADRead) not found exactly once in decompressed state")
    base1 = idx1 - (ANCHOR_1_ADDR - MEM1_BASE_VADDR)

    idx2 = decompressed.find(anchor2)
    if idx2 == -1 or decompressed.find(anchor2, idx2 + 1) != -1:
        raise RuntimeError("Anchor 2 (menuFightMainCtrl) not found exactly once in decompressed state")
    base2 = idx2 - (ANCHOR_2_ADDR - MEM1_BASE_VADDR)

    if base1 != base2:
        raise RuntimeError(f"Anchor cross-check MISMATCH: base1=0x{base1:X} base2=0x{base2:X}")

    return base1


def main():
    elf = ElfReader(ELF_PATH)

    files = sys.argv[1:]
    if not files:
        print("Usage: python _phase0_scratch_savestate_diff.py <state1.sav> <state2.sav> ...")
        return 1

    mem1_blocks = []
    for path in files:
        print(f"Parsing {path} ...")
        decompressed = parse_and_decompress(path)
        print(f"  Decompressed size: {len(decompressed)} bytes")
        base = find_mem1_base(decompressed, elf)
        print(f"  MEM1 base offset in decompressed buffer: 0x{base:X}")
        mem1 = decompressed[base:base + MEM1_SIZE]
        if len(mem1) != MEM1_SIZE:
            raise RuntimeError(f"{path}: truncated MEM1 extraction ({len(mem1)} bytes)")
        mem1_blocks.append((path, mem1))

    out_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(out_dir, exist_ok=True)
    for path, mem1 in mem1_blocks:
        dump_path = os.path.join(out_dir, os.path.basename(path) + ".mem1.bin")
        with open(dump_path, "wb") as f:
            f.write(mem1)
        print(f"  Wrote raw MEM1 dump: {dump_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
