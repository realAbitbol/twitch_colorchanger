"""
Global config watcher instance for coordinating bot-initiated config changes
"""

_GLOBAL_WATCHER = None


def set_global_watcher(watcher):
    """Set the global config watcher instance"""
    global _GLOBAL_WATCHER  # pylint: disable=global-statement
    _GLOBAL_WATCHER = watcher


def pause_config_watcher():
    """Pause the global config watcher if it exists"""
    if _GLOBAL_WATCHER:
        _GLOBAL_WATCHER.pause_watching()


def resume_config_watcher():
    """Resume the global config watcher if it exists"""
    if _GLOBAL_WATCHER:
        _GLOBAL_WATCHER.resume_watching()
