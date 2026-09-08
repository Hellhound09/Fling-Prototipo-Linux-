"""Instalador de .NET 4.8 usando GE-Proton MSI (principal) + Microsoft GUI (fallback)."""

import subprocess
import os
import time
import tempfile
import urllib.request
from pathlib import Path
from typing import Tuple, Optional, Callable, List
import logging

logger = logging.getLogger(__name__)

# URL oficial Microsoft .NET 4.8 Runtime (offline installer)
DOTNET48_URL = "https://go.microsoft.com/fwlink/?linkid=2088631"
DOTNET48_FILENAME = "NDP48-x86-x64-AllOS-ENU.exe"


class DotNetInstaller:
    """Instalador de .NET 4.8 con estrategias ordenadas por fiabilidad."""

    def __init__(self, prefix_path: Path, proton_path: Path, parent_window=None):
        self.prefix_path = Path(prefix_path)
        self.proton_path = Path(proton_path)
        self.parent_window = parent_window
        self.wine_bin = self._find_wine_bin()
        self.ge_proton_wine = self._find_ge_proton_wine()

    def _find_wine_bin(self) -> Optional[Path]:
        """Encuentra wine en el Proton del juego."""
        candidates = [
            self.proton_path / "files" / "bin" / "wine",
            self.proton_path / "dist" / "bin" / "wine",
            self.proton_path / "bin" / "wine",
        ]
        for c in candidates:
            if c.exists():
                return c
        # Fallback: system wine
        system_wine = Path("/usr/bin/wine")
        return system_wine if system_wine.exists() else None

    def _find_ge_proton_wine(self) -> Optional[Path]:
        """Busca wine de GE-Proton en herramientas de compatibilidad de Steam."""
        ge_paths = [
            Path.home() / ".local/share/Steam/compatibilitytools.d",
            Path("/usr/share/steam/compatibilitytools.d"),
            Path("/opt/steam/compatibilitytools.d"),
        ]
        
        for base in ge_paths:
            if base.exists():
                for ge_dir in sorted(base.glob("GE-Proton*"), reverse=True):
                    candidates = [
                        ge_dir / "files" / "bin" / "wine",
                        ge_dir / "dist" / "bin" / "wine",
                        ge_dir / "bin" / "wine",
                    ]
                    for c in candidates:
                        if c.exists():
                            logger.info(f"GE-Proton wine encontrado: {c}")
                            return c
        return None

    def download_dotnet48(self, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """Descarga el instalador offline de .NET 4.8 desde Microsoft."""
        try:
            if progress_callback:
                progress_callback("Descargando .NET 4.8 Runtime desde Microsoft...")

            temp_dir = Path(tempfile.gettempdir())
            installer_path = temp_dir / DOTNET48_FILENAME

            def reporthook(block_num, block_size, total_size):
                if progress_callback and total_size > 0:
                    percent = min(100, (block_num * block_size * 100) // total_size)
                    progress_callback(f"Descargando .NET 4.8... {percent}%")

            urllib.request.urlretrieve(DOTNET48_URL, installer_path, reporthook)

            if installer_path.exists() and installer_path.stat().st_size > 1000000:
                return True, str(installer_path)
            else:
                return False, "Descarga incompleta o archivo corrupto"

        except Exception as e:
            return False, f"Error descargando .NET 4.8: {e}"

    def install_via_ge_proton_msi(self, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Instala .NET 4.8 usando MSI oficial con wine de GE-Proton.
        GE-Proton tiene parches para que el instalador MSI funcione correctamente.
        """
        if not self.ge_proton_wine:
            return False, "GE-Proton no encontrado. Instale GE-Proton desde Steam > Configuración > Compatibilidad."

        if not self.wine_bin:
            return False, "No se encontró wine binario"

        # Descargar instalador si no existe localmente
        if progress_callback:
            progress_callback("Descargando instalador .NET 4.8 desde Microsoft...")
        
        success, result = self.download_dotnet48(progress_callback)
        if not success:
            return False, f"Error descargando instalador: {result}"
        
        installer_path = result

        if progress_callback:
            progress_callback("Instalando .NET 4.8 via GE-Proton MSI (ventana de progreso aparecerá)...")

        env = os.environ.copy()
        env['WINEPREFIX'] = str(self.prefix_path)
        env['LC_ALL'] = 'C'
        env['LANG'] = 'C'
        env['LANGUAGE'] = 'C'
        env['DISPLAY'] = os.environ.get('DISPLAY', ':0')
        env['WINEHEADLESS'] = '0'
        env['MESA_LOADER_DRIVER_OVERRIDE'] = ''

        log_file = str(self.prefix_path / "dotnet48_ge_install.log")
        
        # Usar wine de GE-Proton para ejecutar MSI
        cmd = [
            str(self.ge_proton_wine), 'msiexec',
            '/i', installer_path,
            '/qb', '/norestart',  # /qb = UI básica con progreso
            '/l*v', log_file
        ]

        try:
            if progress_callback:
                progress_callback("Ejecutando instalador .NET 4.8 via GE-Proton...")

            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1200, errors='replace')

            # Verificar instalación exitosa
            time.sleep(3)
            
            # Leer log para diagnóstico
            install_log = ""
            if Path(log_file).exists():
                install_log = Path(log_file).read_text(encoding='utf-8', errors='replace')

            if result.returncode in (0, 3010):
                # Verificar instalación real
                from .detector import DotNetDetector
                detector = DotNetDetector(self.prefix_path)
                if detector.is_dotnet48_installed()[0]:
                    return True, ".NET 4.8 instalado correctamente via GE-Proton MSI"
                
            error_detail = f"GE-Proton MSI terminó (código {result.returncode}) pero verificación falló"
            if Path(log_file).exists():
                install_log = Path(log_file).read_text(encoding='utf-8', errors='replace')
                error_lines = [l.strip() for l in install_log.split('\n') if any(kw in l.lower() for kw in ['error', 'fail', 'fatal', 'roll back'])]
                if error_lines:
                    error_detail += f"\nErrores: {'; '.join(error_lines[-10:])}"
            
            return False, error_detail

        except subprocess.TimeoutExpired:
            return False, f"Timeout instalando .NET 4.8 via GE-Proton (20 min). Log: {log_file}"
        except Exception as e:
            return False, f"Error ejecutando GE-Proton MSI: {e}"

    def install_via_microsoft_gui(self, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Instala .NET 4.8 usando el instalador gráfico completo de Microsoft (fallback).
        Ejecuta el .exe directamente con Wine para GUI completa (como Windows).
        """
        if not self.wine_bin:
            return False, "No se encontró wine binario"

        if progress_callback:
            progress_callback("Descargando instalador .NET 4.8 desde Microsoft...")
        
        success, result = self.download_dotnet48(progress_callback)
        if not success:
            return False, f"Error descargando instalador: {result}"
        
        installer_path = result

        if progress_callback:
            progress_callback("Ejecutando instalador .NET 4.8 de Microsoft (GUI completa)...")

        env = os.environ.copy()
        env['WINEPREFIX'] = str(self.prefix_path)
        env['LC_ALL'] = 'C'
        env['LANG'] = 'C'
        env['LANGUAGE'] = 'C'
        env['DISPLAY'] = os.environ.get('DISPLAY', ':0')
        env['WINEHEADLESS'] = '0'
        env['MESA_LOADER_DRIVER_OVERRIDE'] = ''

        log_file = str(self.prefix_path / "dotnet48_microsoft_install.log")
        
        # Ejecutar .exe directamente con Wine (GUI completa, SIN /qb ni /qn)
        cmd = [
            str(self.wine_bin), installer_path,
            '/norestart',
            '/l*v', log_file
        ]

        try:
            if progress_callback:
                progress_callback("Ejecutando instalador Microsoft .NET 4.8 (GUI completa)...")

            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800, errors='replace')

            time.sleep(3)
            
            # Verificar instalación
            from .detector import DotNetDetector
            detector = DotNetDetector(self.prefix_path)
            if detector.is_dotnet48_installed()[0]:
                return True, ".NET 4.8 instalado correctamente via Microsoft GUI"

            error_detail = f"Instalador Microsoft terminó (código {result.returncode}) pero verificación falló"
            if Path(log_file).exists():
                install_log = Path(log_file).read_text(encoding='utf-8', errors='replace')
                error_lines = [l.strip() for l in install_log.split('\n') if any(kw in l.lower() for kw in ['error', 'fail', 'fatal', 'roll back'])]
                if error_lines:
                    error_detail += f"\nErrores: {'; '.join(error_lines[-10:])}"
            
            return False, error_detail

        except subprocess.TimeoutExpired:
            return False, f"Timeout instalando .NET 4.8 via Microsoft GUI (30 min). Log: {log_file}"
        except Exception as e:
            return False, f"Error ejecutando instalador Microsoft: {e}"

    def install(self, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Intenta instalar .NET 4.8 con estrategias ordenadas por fiabilidad.
        """
        strategies = [
            ("GE-Proton MSI", self.install_via_ge_proton_msi),
            ("Microsoft GUI", self.install_via_microsoft_gui),
        ]

        for name, strategy in strategies:
            if progress_callback:
                progress_callback(f"Intentando {name}...")
            
            success, msg = strategy(progress_callback)
            if success:
                return True, f".NET 4.8 instalado correctamente via {name}: {msg}"
            
            logger.warning(f"Estrategia {name} falló: {msg}")
            if progress_callback:
                progress_callback(f"{name} falló: {msg[:100]}")

        return False, "Todas las estrategias de instalación .NET 4.8 fallaron"