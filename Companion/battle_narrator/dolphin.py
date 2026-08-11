import time

from .memory import MemoryError, MemoryReader


class DolphinConnectionError(RuntimeError):
    pass


class UnsupportedGameError(DolphinConnectionError):
    pass


def read_disc_label(memory, profile):
    """The disc header's game ID and revision.

    Reported and logged, never used as the compatibility gate -- see
    `profile.engine_signatures` for why the label answers the wrong
    question."""
    header = memory.bytes(profile.mem1_start, 8, "GameCube disc header")
    return header[:6], header[7]


def engine_mismatches(memory, profile):
    """Signatures whose bytes are not what `profile` assumes.

    Returns a list of (name, address, expected, found); empty means the
    loaded binary is laid out the way every address in the profile
    expects."""
    mismatches = []
    for name, address, expected in profile.engine_signatures:
        found = memory.bytes(
            address, len(expected), f"engine signature {name}")
        if found != expected:
            mismatches.append((name, address, expected, found))
    return mismatches


def engine_not_loaded(mismatches, total):
    """True only when EVERY signature is missing and reads as zeroes.

    That is what a not-yet-booted game looks like: MEM1 is cleared and the
    DOL's .text has not been copied in. It must be reported as "not ready
    yet, retry" rather than "wrong game" -- treating it as the latter would
    make the narrator refuse to start whenever it attached a moment too
    early.

    Requiring ALL of them matters. An earlier version asked only whether
    the *failing* signatures were zero, which meant a build that matched
    seven signatures and zeroed the eighth was reported as "still
    booting" and retried forever, instead of being refused. Booting zeroes
    everything; a partial match is a real mismatch."""
    return len(mismatches) == total and total > 0 and all(
        found == bytes(len(found)) for _, _, _, found in mismatches)


def describe_mismatch(profile, label, revision, mismatches):
    name, address, expected, found = mismatches[0]
    return (
        f"This is not a build {profile.label} can read. "
        f"Disc reports {label} revision {revision}. "
        f"{len(mismatches)} of {len(profile.engine_signatures)} engine "
        f"checks failed; the first was {name} at 0x{address:08X} "
        f"(expected {expected.hex()}, found {found.hex()}). "
        "Running anyway would misread memory and speak wrong information."
    )


class DolphinConnection:
    def __init__(self, backend, profile, retry_seconds=0.25):
        self.backend = backend
        self.profile = profile
        self.retry_seconds = retry_seconds
        self.memory = MemoryReader(backend, profile)
        self.connected = False

    def attach(self):
        self.backend.hook()
        if not self.backend.is_hooked():
            status = self.backend.get_status()
            raise DolphinConnectionError(f"Dolphin is not readable: {status}")
        self.connected = True
        try:
            self.verify_profile()
        except Exception:
            self.close()
            raise
        return self.memory

    def verify_profile(self):
        """Accept any build whose engine matches, whatever the disc says.

        This is what makes the narrator work on XG and other US-based hacks
        without a per-hack profile: they relabel the disc but do not move
        the engine. It is also what keeps a genuinely different build (PAL,
        JP retail) out, which the old label check only did by accident --
        a hack that kept the label would have sailed through it."""
        game_id, revision = read_disc_label(self.memory, self.profile)
        label = game_id.decode("ascii", errors="replace")
        mismatches = engine_mismatches(self.memory, self.profile)
        if not mismatches:
            return label, revision
        raise UnsupportedGameError(
            describe_mismatch(self.profile, label, revision, mismatches))

    def is_readable(self):
        try:
            return bool(self.backend.is_hooked())
        except Exception:
            return False

    def close(self):
        if self.connected:
            try:
                self.backend.un_hook()
            finally:
                self.connected = False

    def wait_until_attached(self, attempts=1):
        last = None
        for _ in range(attempts):
            try:
                return self.attach()
            except DolphinConnectionError as exc:
                last = exc
                time.sleep(self.retry_seconds)
        raise last or DolphinConnectionError("Dolphin is not running")


def classify_disconnect(exc):
    if isinstance(exc, MemoryError):
        return "Dolphin memory became unreadable"
    return f"Dolphin disconnected: {exc}"
