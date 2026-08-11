from .dolphin import (
    describe_mismatch, engine_mismatches, engine_not_loaded, read_disc_label,
)
from .memory import MemoryError, MemoryReader


class ConnectionError(RuntimeError):
    pass


class ProfileNotReady(ConnectionError):
    pass


class UnsupportedProfile(ConnectionError):
    pass


class PersistentDolphinConnection:
    def __init__(self, backend, profile):
        self.backend = backend
        self.profile = profile
        self.memory = MemoryReader(backend, profile)
        self.connected = False

    def hook(self):
        self.backend.hook()
        if not self.backend.is_hooked():
            raise ConnectionError(
                f"Dolphin is not readable: {self.backend.get_status()}"
            )
        self.connected = True
        return self.memory

    def verify_profile(self):
        """Gate on the engine's actual code, not on the disc label.

        Every address this narrator uses is a position in the game's code,
        so the question that matters is "is this binary laid out the way
        those addresses assume", not "what does the disc call itself". A
        ROM hack built on the US release -- XG, which this whole project
        exists for -- keeps the layout while being free to relabel the
        disc, and the old label check refused exactly those builds.

        Returns the disc label so callers can log what actually attached;
        a label other than the profile's canonical one is informative (it
        means a hack), not a problem."""
        game_id, revision = read_disc_label(self.memory, self.profile)
        if game_id == b"\0" * 6:
            raise ProfileNotReady("Game profile is not identifiable yet")
        mismatches = engine_mismatches(self.memory, self.profile)
        if engine_not_loaded(mismatches, len(self.profile.engine_signatures)):
            # Disc header is present but the DOL's code has not been copied
            # into MEM1 yet. Retryable, not a wrong-game verdict.
            raise ProfileNotReady("Game code is not loaded yet")
        if mismatches:
            raise UnsupportedProfile(describe_mismatch(
                self.profile, game_id.decode("ascii", errors="replace"),
                revision, mismatches))
        return game_id.decode("ascii", errors="replace"), revision

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
