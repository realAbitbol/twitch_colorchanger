"""Deprecated shim: moved to token.manager.

This module remains temporarily for backward compatibility. Import from
`token.manager` instead. Will be removed after refactor rollout.
"""

from .token.manager import TokenManager  # type: ignore

__all__ = ["TokenManager"]
