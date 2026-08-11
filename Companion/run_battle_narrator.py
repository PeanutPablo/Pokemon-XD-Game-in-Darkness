"""Canonical production entry point for the read-only vanilla-XD narrator."""

import sys

from battle_narrator.phase1b_app import run


if __name__ == "__main__":
    sys.exit(run())