"""Manager subsystem package.

Aggregates bot management helper components (health, reconnect, statistics).
"""

from .health import HealthMonitor
from .reconnect import attempt_bot_reconnection, reconnect_unhealthy_bots
from .statistics import ManagerStatistics

__all__ = [
    "HealthMonitor",
    "reconnect_unhealthy_bots",
    "attempt_bot_reconnection",
    "ManagerStatistics",
]
