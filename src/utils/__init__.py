"""Utility functions package for the Twitch color changer application.

This package provides various helper functions for formatting, logging, and
other common operations used throughout the application.

Exposed functions:
    format_duration: Formats time durations into human-readable strings.
    emit_startup_instructions: Emits startup instructions for the application.
"""

from .helpers import emit_startup_instructions, format_duration

__all__ = ["format_duration", "emit_startup_instructions"]
