"""Módulos core para Fling Trainer Manager."""

from .system_deps import SystemDepsManager
from .wine_env import WineEnvManager
from .winetricks_mgr import WinetricksManager

__all__ = [
    "SystemDepsManager",
    "WineEnvManager",
    "WinetricksManager",
]