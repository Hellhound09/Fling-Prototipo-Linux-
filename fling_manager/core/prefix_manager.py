import subprocess
import os
import sys
import tkinter as tk
from tkinter import simpledialog, messagebox
from typing import List, Optional, Tuple
from pathlib import Path
import time
import urllib.request
import tempfile

from .system_deps import SystemDepsManager
from .wine_env import WineEnvManager
from .winetricks_mgr import WinetricksManager
from .dotnet.manager import DotNetManager, DotNetResult
from .dotnet.detector import DotNetDetector
from .sudo_helper import SudoHelper


class PrefixManager:
    """Gestiona prefijos Wine: instalación de dependencias, winetricks, .NET, etc."""

    def __init__(self, prefix_path: str, proton_path: str, parent_window: Optional[tk.Tk] = None):
        self.prefix_path = Path(prefix_path)
        self.proton_path = Path(proton_path)
        self.parent = parent_window
        
        # Herramientas base
        self.wine_bin = self._find_wine_bin()
        self.winetricks_path = self._find_winetricks()
        
        # Gestores modulares
        self.system_deps = SystemDepsManager(parent_window)
        self.wine_env = WineEnvManager(self.prefix_path, self.proton_path)
        self.winetricks_mgr = WinetricksManager(self.prefix_path, self.wine_bin, self.winetricks_path)
        self.dotnet_mgr = DotNetManager(self.prefix_path, self.proton_path)
        
        # Configurar herramientas en gestores
        self.wine_env.set_tools(self.wine_bin, self.winetricks_path)
        self.system_deps.parent_window = parent_window

    def _find_wine_bin(self) -> Optional[Path]:
        """Encuentra el binario wine dentro del Proton."""
        candidates = [
            self.proton_path / "files" / "bin" / "wine",
            self.proton_path / "dist" / "bin" / "wine",
            self.proton_path / "bin" / "wine",
        ]
        for c in candidates:
            if c.exists():
                return c
        system_wine = Path("/usr/bin/wine")
        return system_wine if system_wine.exists() else None

    def _find_winetricks(self) -> Optional[Path]:
        """Encuentra winetricks."""
        candidates = [
            Path("/usr/bin/winetricks"),
            Path("/usr/local/bin/winetricks"),
            Path.home() / ".local/bin/winetricks",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def install_full_profile(self, dotnet_installer: Optional[str] = None,
                             install_system_deps: bool = True,
                             progress_callback=None) -> Tuple[bool, str]:
        """
        Instala perfil completo: sistema 32-bit → Wine prep → .NET 4.8 → winetricks.
        Flujo reproducible y ordenado para cualquier prefijo.
        """
        results = []

        # 1. Dependencias de sistema (32-bit)
        if install_system_deps:
            if progress_callback:
                progress_callback("Verificando dependencias de sistema (32-bit)...")
            success, msg = self.system_deps.install(progress_callback)
            results.append(("Sistema 32-bit", success, msg))
            if not success:
                return False, f"Fallo en dependencias de sistema: {msg}"

        # 2. Preparar entorno Wine (win10, riched30, DLL overrides)
        if progress_callback:
            progress_callback("Preparando entorno Wine (Windows 10)...")
        success, msg = self.wine_env.prepare(progress_callback)
        results.append(("Wine prep", success, msg))
        if not success:
            return False, f"Fallo preparando Wine: {msg}"

        # 3. .NET 4.8 Runtime (GE-Proton MSI principal, Microsoft GUI fallback)
        if progress_callback:
            progress_callback("Instalando .NET 4.8 Runtime (GE-Proton MSI)...")
        dotnet_result: DotNetResult = self.dotnet_mgr.ensure_dotnet48(progress_callback)
        results.append((".NET 4.8", dotnet_result.success, dotnet_result.message))
        if not dotnet_result.success and not dotnet_result.is_partial:
            # Solo fallar si no hay ni instalación parcial
            return False, f"Fallo crítico en .NET 4.8: {dotnet_result.message}"
        elif dotnet_result.is_partial:
            if progress_callback:
                progress_callback(f"⚠ {dotnet_result.message}. Continuando con versión parcial...")

        # 4. Winetricks dependencias requeridas (vcrun2019, d3dx, corefonts)
        if progress_callback:
            progress_callback("Instalando dependencias Wine requeridas (vcrun2019, d3dx, corefonts)...")
        success, msg = self.winetricks_mgr.install_all(progress_callback)
        results.append(("Winetricks", success, msg))
        if not success:
            return False, f"Fallo en winetricks requeridas: {msg}"

        return True, "Perfil completo instalado:\n" + "\n".join(f"  {'✓' if r[1] else '⚠'} {r[0]}" for r in results)

    def install_base_profile(self, install_system_deps: bool = True,
                             progress_callback=None) -> Tuple[bool, str]:
        """
        Instala perfil base SIN .NET: sistema 32-bit → Wine prep → winetricks requeridas.
        Para prefixes que ya tienen .NET o no lo necesitan.
        """
        results = []

        # 1. Dependencias de sistema (32-bit)
        if install_system_deps:
            if progress_callback:
                progress_callback("Verificando dependencias de sistema (32-bit)...")
            success, msg = self.system_deps.install(progress_callback)
            results.append(("Sistema 32-bit", success, msg))
            if not success:
                return False, f"Fallo en dependencias de sistema: {msg}"

        # 2. Preparar entorno Wine (win10, riched30, DLL overrides)
        if progress_callback:
            progress_callback("Preparando entorno Wine (Windows 10)...")
        success, msg = self.wine_env.prepare(progress_callback)
        results.append(("Wine prep", success, msg))
        if not success:
            return False, f"Fallo preparando Wine: {msg}"

        # 3. Winetricks solo requeridas (d3dx9, d3dx10, d3dx11_43, corefonts)
        if progress_callback:
            progress_callback("Instalando dependencias Wine requeridas (d3dx, corefonts)...")
        success, msg = self.winetricks_mgr.install_required_only(progress_callback)
        results.append(("Winetricks base", success, msg))
        if not success:
            return False, f"Fallo en winetricks requeridas: {msg}"

        return True, "Perfil base instalado:\n" + "\n".join(f"  {'✓' if r[1] else '⚠'} {r[0]}" for r in results)

    def run_in_prefix(self, command: List[str], env_vars: Optional[dict] = None) -> Tuple[int, str, str]:
        """Ejecuta comando dentro del prefijo Wine."""
        if not self.wine_bin:
            return -1, "", "No wine binary"

        env = os.environ.copy()
        env['WINEPREFIX'] = str(self.prefix_path)
        if env_vars:
            env.update(env_vars)

        try:
            result = subprocess.run(
                [str(self.wine_bin)] + command,
                env=env,
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except Exception as e:
            return -1, "", str(e)

    def run_proton_command(self, command: List[str], env_vars: Optional[dict] = None) -> Tuple[int, str, str]:
        """Ejecuta comando usando proton run."""
        env = os.environ.copy()
        env['WINEPREFIX'] = str(self.prefix_path)
        if env_vars:
            env.update(env_vars)

        try:
            result = subprocess.run(
                [str(self.proton_path), 'run'] + command,
                env=env,
                capture_output=True,
                text=True,
                timeout=120
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Timeout"
        except Exception as e:
            return -1, "", str(e)

    def verify_installation(self) -> dict:
        """Verifica estado completo de la instalación."""
        results = {}
        
        # .NET 4.8
        dotnet_installed, dotnet_details = DotNetDetector(self.prefix_path).is_dotnet48_installed()
        results['dotnet48'] = {'installed': dotnet_installed, 'details': dotnet_details}
        
        return results