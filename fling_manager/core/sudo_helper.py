"""Helper para sudo con GUI usando SUDO_ASKPASS."""

import subprocess
import os
import tkinter as tk
from tkinter import simpledialog
from typing import List, Tuple, Optional
import tempfile
import stat


class SudoAskPassHelper:
    """Maneja sudo con prompt de contraseña vía GUI usando SUDO_ASKPASS."""

    def __init__(self, parent_window: Optional[tk.Tk] = None):
        self.parent = parent_window
        self._askpass_script = None
        self._create_askpass_script()

    def _create_askpass_script(self) -> str:
        """Crea un script askpass que use tkinter para pedir la contraseña."""
        script_content = '''#!/usr/bin/env python3
import tkinter as tk
from tkinter import simpledialog
import sys

# Crear ventana raíz oculta
root = tk.Tk()
root.withdraw()

# Obtener el mensaje del prompt desde argumentos o stdin
prompt = "Se requiere contraseña de sudo:"
if len(sys.argv) > 1:
    prompt = sys.argv[1]

# Mostrar diálogo
password = simpledialog.askstring("Autenticación requerida", prompt, show='*')

if password:
    print(password)
    sys.exit(0)
else:
    sys.exit(1)
'''

        # Crear archivo temporal
        fd, path = tempfile.mkstemp(prefix='fling_askpass_', suffix='.py', text=True)
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(script_content)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            self._askpass_script = path
            return path
        except Exception:
            if self._askpass_script and os.path.exists(self._askpass_script):
                os.unlink(self._askpass_script)
            raise

    def run_with_sudo(self, command: List[str], prompt_message: str = "", timeout: int = 120) -> Tuple[bool, str]:
        """
        Ejecuta comando con sudo usando askpass GUI.
        timeout: tiempo máximo en segundos (default 120s, usar 300 para instalaciones de paquetes)
        """
        if not self._askpass_script:
            self._create_askpass_script()

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

        # 2. Usar sudo con askpass
        env = os.environ.copy()
        env['SUDO_ASKPASS'] = self._askpass_script

        # Construir mensaje para el prompt
        if not prompt_message:
            prompt_message = f"Se requiere contraseña para:\\n{' '.join(command)}"

        try:
            result = subprocess.run(
                ['sudo', '-A'] + command,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, f"Timeout ejecutando comando con sudo ({timeout}s)"
        except Exception as e:
            return False, str(e)

    def cleanup(self):
        """Limpia el script askpass temporal."""
        if self._askpass_script and os.path.exists(self._askpass_script):
            try:
                os.unlink(self._askpass_script)
            except Exception:
                pass
            self._askpass_script = None

    def __del__(self):
        self.cleanup()


def run_with_sudo_gui(command: List[str], parent: Optional[tk.Tk] = None, prompt_message: str = "", timeout: int = 120) -> Tuple[bool, str]:
    """
    Función de conveniencia para ejecutar comando con sudo y GUI.
    timeout: tiempo máximo en segundos (default 120s)
    """
    helper = SudoAskPassHelper(parent)
    try:
        return helper.run_with_sudo(command, prompt_message, timeout)
    finally:
        helper.cleanup()


class SudoHelper:
    """Wrapper que mantiene compatibilidad con la API existente."""

    def __init__(self, parent_window: Optional[tk.Tk] = None):
        self.helper = SudoAskPassHelper(parent_window)

    def run_with_sudo(self, command: List[str], parent: Optional[tk.Tk] = None,
                      prompt_message: str = "", timeout: int = 120) -> Tuple[bool, str]:
        return self.helper.run_with_sudo(command, prompt_message, timeout)

    @staticmethod
    def check_sudo_available() -> bool:
        """Verifica si sudo está disponible y usuario está en sudoers."""
        try:
            result = subprocess.run(['sudo', '-n', 'true'], capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False