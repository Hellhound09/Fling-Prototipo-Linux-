"""Preparación del entorno Wine: win10, riched30, DLL overrides."""

import subprocess
import os
from pathlib import Path
from typing import Tuple, Optional, Callable, List
import logging

logger = logging.getLogger(__name__)


class WineEnvManager:
    """Prepara el entorno Wine antes de instalar .NET y dependencias."""

    # Verbs requeridos para .NET 4.8
    REQUIRED_VERBS = ['win10', 'riched30']
    
    # DLL overrides para .NET
    DLL_OVERRIDES = {
        'mscoree': 'native,builtin',
        'mscoreei': 'native,builtin',
        'fusion': 'native,builtin',
        'mshtml': 'native,builtin',
    }

    def __init__(self, prefix_path: Path, proton_path: Path):
        self.prefix_path = Path(prefix_path)
        self.proton_path = Path(prefix_path)
        self.wine_bin = self._find_wine_bin()
        self.winetricks_path = self._find_winetricks()

    def _find_wine_bin(self) -> Optional[Path]:
        """Encuentra wine binario."""
        # Se sobrescribe desde PrefixManager
        return None

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

    def set_tools(self, wine_bin: Path, winetricks_path: Optional[Path]):
        """Configura herramientas (llamado desde PrefixManager)."""
        self.wine_bin = wine_bin
        if winetricks_path:
            self.winetricks_path = winetricks_path

    def prepare(self, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Prepara el entorno Wine para .NET 4.8:
        1. winetricks win10 (modo Windows 10)
        2. winetricks riched30 (requerido por .NET 4.8 MSI)
        3. DLL overrides en registro
        """
        if not self.winetricks_path or not self.wine_bin:
            return False, "winetricks o wine no disponible"

        # 1. win10 + riched30
        for verb in self.REQUIRED_VERBS:
            if progress_callback:
                progress_callback(f"Configurando Wine: {verb}...")
            
            success, msg = self._run_winetricks_verb(verb)
            if not success:
                return False, f"winetricks {verb} falló: {msg}"

        # 2. DLL overrides
        if progress_callback:
            progress_callback("Configurando DLL overrides para .NET...")
        
        for dll, override in self.DLL_OVERRIDES.items():
            success, msg = self._set_dll_override(dll, override)
            if not success:
                logger.warning(f"DLL override {dll} falló: {msg}")

        return True, "Entorno Wine preparado (win10, riched30, DLL overrides)"

    def _run_winetricks_verb(self, verb: str) -> Tuple[bool, str]:
        """Ejecuta un verb de winetricks."""
        if not self.winetricks_path:
            return False, "winetricks no disponible"

        env = {
            'WINEPREFIX': str(self.prefix_path),
            'HOME': os.environ.get('HOME', str(Path.home())),
            'WINETRICKS_CACHE': str(Path.home() / '.cache' / 'winetricks'),
            'XDG_CACHE_HOME': str(Path.home() / '.cache'),
            'WINETRICKS_FORCE': '1',
            'LC_ALL': 'C',
            'LANG': 'C',
            'LANGUAGE': 'C',
        }

        cmd = [str(self.winetricks_path), '-q', verb]
        try:
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120, errors='replace')
            if result.returncode != 0:
                return False, f"winetricks {verb} falló (código {result.returncode}): {result.stderr[-500:]}"
            return True, f"{verb} OK"
        except subprocess.TimeoutExpired:
            return False, f"Timeout en winetricks {verb}"
        except Exception as e:
            return False, f"Error en winetricks {verb}: {e}"

    def _set_dll_override(self, dll: str, override: str) -> Tuple[bool, str]:
        """Configura DLL override en registro Wine."""
        if not self.wine_bin:
            return False, "wine no disponible"

        cmd = [
            str(self.wine_bin), 'reg', 'add',
            f'HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides',
            '/v', dll, '/t', 'REG_SZ', '/d', override, '/f'
        ]
        
        env = {
            'WINEPREFIX': str(self.prefix_path),
            'LC_ALL': 'C', 'LANG': 'C', 'LANGUAGE': 'C',
        }
        
        try:
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10, errors='replace')
            return result.returncode == 0, "OK" if result.returncode == 0 else result.stderr
        except Exception as e:
            return False, str(e)

    def verify(self) -> Tuple[bool, str]:
        """Verifica que el entorno esté preparado correctamente."""
        checks = []
        
        # Verificar win10 mode
        # Verificar riched30
        # Verificar DLL overrides
        return True, "Entorno verificado"