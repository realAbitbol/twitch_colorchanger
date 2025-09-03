"""Utility package namespace.

Exports commonly used helper functions so callers can simply import
``from .utils import format_duration`` after the refactor.
"""

from .helpers import emit_startup_instructions, format_duration

__all__ = ["format_duration", "emit_startup_instructions"]
