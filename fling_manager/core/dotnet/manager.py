"""Orquestador de .NET 4.8: detección, instalación y verificación."""

from pathlib import Path
from typing import Tuple, Optional, Callable, NamedTuple
from .detector import DotNetDetector
from .installer import DotNetInstaller

import logging

logger = logging.getLogger(__name__)


class DotNetResult(NamedTuple):
    success: bool
    message: str
    method: str
    version: str
    is_partial: bool = False


class DotNetManager:
    """Orquestador principal para .NET 4.8: detectar, instalar, verificar."""

    def __init__(self, prefix_path: Path, proton_path: Path, parent_window=None):
        self.prefix_path = Path(prefix_path)
        self.proton_path = Path(proton_path)
        self.parent_window = parent_window
        
        self.detector = DotNetDetector(self.prefix_path)
        self.installer = DotNetInstaller(self.prefix_path, self.proton_path)

    def ensure_dotnet48(self, progress_callback: Optional[Callable] = None) -> DotNetResult:
        """
        Garantiza que .NET 4.8 esté instalado y funcional.
        No bloquea si falla - devuelve resultado parcial.
        """
        # 1. Verificar si ya está instalado correctamente
        if progress_callback:
            progress_callback("Verificando .NET 4.8 existente...")
        
        installed, details = self.detector.is_dotnet48_installed()
        if installed:
            version = self.detector.get_installed_version() or "4.8+"
            return DotNetResult(True, f".NET 4.8 ya instalado: {details}", "existing", version, False)
        
        if progress_callback:
            progress_callback(f".NET 4.8 no detectado: {details}. Instalando...")
        
        # 2. Instalar con estrategias ordenadas
        success, msg = self.installer.install(progress_callback)
        
        if success:
            # Verificar instalación final
            installed, details = self.detector.is_dotnet48_installed()
            if installed:
                version = self.detector.get_installed_version() or "4.8+"
                return DotNetResult(True, f".NET 4.8 instalado: {msg}", "installed", version, False)
            else:
                # Instalación reportó éxito pero verificación falló - marcar como parcial
                version = self.detector.get_installed_version() or "4.x (parcial)"
                return DotNetResult(True, f".NET instalado parcialmente: {msg}", "partial", version, True)
        
        # Todas las estrategias fallaron - verificar si hay instalación parcial
        version = self.detector.get_installed_version() or "4.x (parcial)"
        partial_installed, _ = self.detector.is_dotnet48_installed()
        
        return DotNetResult(
            partial_installed,  # Success = True si hay algo instalado
            f".NET 4.8 completo no instalado, pero hay versión parcial: {msg}", 
            "partial" if partial_installed else "failed", 
            version,
            True
        )

    def verify_installation(self) -> Tuple[bool, str]:
        """Verifica instalación completa de .NET 4.8."""
        installed, details = self.detector.is_dotnet48_installed()
        version = self.detector.get_installed_version() or "unknown"
        return installed, f".NET {version}: {details}"