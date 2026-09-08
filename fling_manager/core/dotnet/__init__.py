"""Módulo .NET 4.8 para Fling Trainer Manager."""

from .detector import DotNetDetector
from .installer import DotNetInstaller
from .manager import DotNetManager, DotNetResult

__all__ = [
    "DotNetDetector",
    "DotNetInstaller", 
    "DotNetManager",
    "DotNetResult",
]