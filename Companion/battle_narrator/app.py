"""Compatibility import for the canonical persistent production narrator.

The original one-shot Phase 1A application has been superseded.  Keeping this
module as a thin alias prevents older imports from silently losing verified
lifecycle, menu, GSmsg-substitution, and health narration features.
"""

from .phase1b_app import parser as build_parser
from .phase1b_app import run

__all__ = ["build_parser", "run"]