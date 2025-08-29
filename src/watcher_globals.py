"""
Global config watcher instance for coordinating bot-initiated config changes
"""

_global_watcher = None

def set_global_watcher(watcher):
    """Set the global config watcher instance"""
    global _global_watcher
    _global_watcher = watcher

def pause_config_watcher():
    """Pause the global config watcher if it exists"""
    if _global_watcher:
        _global_watcher.pause_watching()

def resume_config_watcher():
    """Resume the global config watcher if it exists"""
    if _global_watcher:
        _global_watcher.resume_watching()
