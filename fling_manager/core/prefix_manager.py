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


class SudoHelper:
    """Maneja ejecución de comandos con sudo, pidiendo password si es necesario."""

    @staticmethod
    def run_with_sudo(command: List[str], parent: Optional[tk.Tk] = None,
                      prompt_message: str = "") -> Tuple[bool, str]:
        """
        Ejecuta comando con sudo. Pide password si es necesario.
        Returns: (success, output)
        """
        # 1. Intentar sin password (sudo -n)
        try:
            result = subprocess.run(
                ['sudo', '-n'] + command,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True, result.stdout
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

        # 2. Pedir password si hay ventana padre
        if parent:
            # Asegurar que la ventana esté visible para el diálogo
            was_withdrawn = False
            try:
                if parent.state() == 'withdrawn':
                    parent.deiconify()
                    was_withdrawn = True
                    parent.update_idletasks()
            except tk.TclError:
                pass  # Ventana destruida o error
            
            if not prompt_message:
                prompt_message = f"Se requiere contraseña para:\n{' '.join(command)}"
            password = SudoHelper._ask_password(parent, prompt_message)
            
            if was_withdrawn:
                try:
                    parent.withdraw()
                except tk.TclError:
                    pass
                
            if not password:
                return False, "Usuario canceló autenticación"
        else:
            # Sin GUI, intentar con sudo normal (pedirá en terminal)
            try:
                result = subprocess.run(
                    ['sudo'] + command,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                return result.returncode == 0, result.stdout + result.stderr
            except Exception as e:
                return False, str(e)

        # 3. Ejecutar con password via stdin
        if not password:
            return False, "No se obtuvo contraseña"
            
        try:
            result = subprocess.run(
                ['sudo', '-S'] + command,
                input=password + '\n',
                capture_output=True,
                text=True,
                timeout=120
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Timeout ejecutando comando"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _ask_password(parent: tk.Tk, message: str) -> Optional[str]:
        """Muestra diálogo modal para pedir password."""
        dialog = tk.Toplevel(parent)
        dialog.title("Autenticación requerida")
        dialog.resizable(False, False)
        dialog.transient(parent)
        dialog.grab_set()

        # Centrar en parent
        dialog.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 200
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 75
        dialog.geometry(f"400x150+{x}+{y}")

        tk.Label(dialog, text=message, wraplength=380, justify=tk.LEFT).pack(pady=15, padx=20)

        entry = tk.Entry(dialog, show="*", font=("Sans", 11))
        entry.pack(pady=5, padx=20, fill=tk.X)
        entry.focus_set()

        result = {'password': None}

        def on_ok():
            result['password'] = entry.get()
            dialog.destroy()

        def on_cancel():
            result['password'] = None
            dialog.destroy()

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="Aceptar", command=on_ok, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancelar", command=on_cancel, width=12).pack(side=tk.LEFT, padx=5)

        dialog.bind('<Return>', lambda e: on_ok())
        dialog.bind('<Escape>', lambda e: on_cancel())
        parent.wait_window(dialog)

        return result['password']

    @staticmethod
    def check_sudo_available() -> bool:
        """Verifica si sudo está disponible y usuario está en sudoers."""
        try:
            result = subprocess.run(['sudo', '-n', 'true'], capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False


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

    def kill_wineserver(self):
        """Mata wineserver para evitar version mismatch."""
        subprocess.run(['pkill', '-9', 'wineserver'], capture_output=True)
        time.sleep(1)

    def verify_installation(self) -> dict:
        """Verifica estado completo de la instalación."""
        results = {}
        
        # .NET 4.8
        dotnet_installed, dotnet_details = DotNetDetector(self.prefix_path).is_dotnet48_installed()
        results['dotnet48'] = {'installed': dotnet_installed, 'details': dotnet_details}
        
        return results