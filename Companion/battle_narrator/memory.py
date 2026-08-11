import struct


class MemoryError(RuntimeError):
    pass


class PointerError(MemoryError):
    pass


def valid_range(address, size, start=0x80000000, end=0x81800000, alignment=1):
    return (
        isinstance(address, int)
        and isinstance(size, int)
        and address != 0
        and size >= 0
        and alignment > 0
        and address % alignment == 0
        and start <= address
        and address + size <= end
    )


def require_range(address, size, label, profile, alignment=1):
    if not valid_range(
        address, size, profile.mem1_start, profile.mem1_end, alignment
    ):
        raise PointerError(
            f"{label}: invalid address 0x{address:08X}, size 0x{size:X}, "
            f"alignment {alignment}"
        )
    return address


class MemoryReader:
    def __init__(self, backend, profile):
        self.backend = backend
        self.profile = profile

    def bytes(self, address, size, label="memory", alignment=1):
        require_range(address, size, label, self.profile, alignment)
        try:
            data = self.backend.read_bytes(address, size)
        except Exception as exc:
            # dolphin_memory_engine can raise a raw RuntimeError (not this
            # project's own MemoryError) on a transient read failure even
            # while Dolphin is still running -- every poll loop in this
            # project already handles MemoryError gracefully (skip this
            # tick, retry next poll), so convert rather than let a raw
            # RuntimeError escape and crash the whole narrator process.
            raise MemoryError(f"{label}: read failed at 0x{address:08X}: {exc}") from exc
        if data is None or len(data) != size:
            raise MemoryError(f"{label}: short read at 0x{address:08X}")
        return bytes(data)

    def u8(self, address, label="u8"):
        return self.bytes(address, 1, label)[0]

    def u16(self, address, label="u16"):
        return int.from_bytes(self.bytes(address, 2, label), "big")

    def u32(self, address, label="u32"):
        return int.from_bytes(self.bytes(address, 4, label, alignment=4), "big")

    def f32(self, address, label="f32"):
        """Big-endian IEEE single. The game keeps a few genuinely
        fractional constants in .rodata -- the Purify Chamber's Flow
        multipliers are the first the narrator needed -- and rounding
        them to integers would silently change a computed value."""
        return struct.unpack(">f", self.bytes(address, 4, label, alignment=4))[0]

    def pointer(self, address, span, label, alignment=4):
        pointer = self.u32(address, f"{label} pointer")
        require_range(pointer, span, label, self.profile, alignment)
        return pointer

    def write_bytes(self, address, data, label="memory", alignment=1):
        """The only write path in this project. Every other reader/reader
        method in this codebase is read-only by design; this exists solely
        for teleport.py's explicitly-scoped, entity-nav-restricted position
        write, at the project owner's explicit request and with explicit
        acceptance of the risk (see teleport.py's module docstring)."""
        require_range(address, len(data), label, self.profile, alignment)
        self.backend.write_bytes(address, bytes(data))

    def gschar(self, address, maximum, label, alignment=1):
        size = (maximum + 1) * 2
        raw = self.bytes(address, size, label, alignment)
        chars = []
        for offset in range(0, size, 2):
            value = (raw[offset] << 8) | raw[offset + 1]
            if value == 0:
                return "".join(chars)
            if value == 0xFFFF:
                raise MemoryError(f"{label}: unresolved control sentinel")
            chars.append(chr(value))
        raise MemoryError(f"{label}: no terminator within {maximum} characters")
