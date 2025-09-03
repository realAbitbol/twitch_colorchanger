"""
Global config watcher instance for coordinating bot-initiated config changes
"""

from __future__ import annotations

from typing import Protocol


class _WatcherProto(Protocol):  # minimal structural typing
    def pause_watching(self) -> None: ...  # noqa: D401,E701 - compact protocol
    def resume_watching(self) -> None: ...


_GLOBAL_WATCHER: _WatcherProto | None = None


def set_global_watcher(watcher: _WatcherProto | None) -> None:
    """Set the global config watcher instance"""
    global _GLOBAL_WATCHER  # pylint: disable=global-statement
    _GLOBAL_WATCHER = watcher


def pause_config_watcher() -> None:
    """Pause the global config watcher if it exists"""
    if _GLOBAL_WATCHER:
        _GLOBAL_WATCHER.pause_watching()


def resume_config_watcher() -> None:
    """Resume the global config watcher if it exists"""
    if _GLOBAL_WATCHER:
        _GLOBAL_WATCHER.resume_watching()
