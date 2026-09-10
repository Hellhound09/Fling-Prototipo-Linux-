"""Gestor de winetricks para dependencias Wine: VC++, D3DX, corefonts."""

import subprocess
import os
from pathlib import Path
from typing import Tuple, Optional, Callable, List
import logging

logger = logging.getLogger(__name__)


class WinetricksManager:
    """Gestiona instalación de dependencias via winetricks con manejo de fallos."""

    # Dependencias REQUERIDAS (fallo = fallo total)
    REQUIRED_VERBS = [
        'd3dx9',          # DirectX 9
        'd3dx10',         # DirectX 10
        'd3dx11_43',      # DirectX 11 (incluye 42)
        'corefonts',      # Fuentes básicas Windows
    ]

    # Dependencias OPCIONALES (fallo = warning, no fallo total)
    OPTIONAL_VERBS = [
        'vcrun2019',      # VC++ 2019 (falla conocido error 102/display en Wine 64-bit)
        'vcrun2022',      # VC++ 2022 (falla conocido error 102)
    ]

    def __init__(self, prefix_path: Path, wine_bin: Path, winetricks_path: Optional[Path] = None):
        self.prefix_path = Path(prefix_path)
        self.wine_bin = wine_bin
        self.winetricks_path = winetricks_path or self._find_winetricks()

    def _find_winetricks(self) -> Optional[Path]:
        """Busca winetricks en el sistema."""
        candidates = [
            Path("/usr/bin/winetricks"),
            Path("/usr/local/bin/winetricks"),
            Path.home() / ".local/bin/winetricks",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def install_all(self, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Instala todas las dependencias winetricks.
        Requeridas: fallo = fallo total
        Opcionales: fallo = warning, continúa
        """
        results = []
        
        # 1. Requeridas
        if progress_callback:
            progress_callback("Instalando dependencias Wine requeridas (vcrun2019, d3dx, corefonts)...")
        
        for verb in self.REQUIRED_VERBS:
            success, msg = self._install_verb(verb, progress_callback, allow_failure=False)
            results.append((verb, success, msg))
            if not success:
                return False, f"Dependencia requerida {verb} falló: {msg}"

        # 2. Opcionales
        if self.OPTIONAL_VERBS:
            if progress_callback:
                progress_callback("Instalando dependencias opcionales (vcrun2022)...")
            
            for verb in self.OPTIONAL_VERBS:
                success, msg = self._install_verb(verb, progress_callback, allow_failure=True)
                # No fallar si opcionales fallan

        return True, "Dependencias Wine instaladas correctamente"

    def install_required_only(self, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Instala solo dependencias REQUERIDAS (d3dx9, d3dx10, d3dx11_43, corefonts).
        No instala opcionales (vcrun2019, vcrun2022).
        """
        results = []
        
        if progress_callback:
            progress_callback("Instalando dependencias Wine requeridas (d3dx, corefonts)...")
        
        for verb in self.REQUIRED_VERBS:
            success, msg = self._install_verb(verb, progress_callback, allow_failure=False)
            results.append((verb, success, msg))
            if not success:
                return False, f"Dependencia requerida {verb} falló: {msg}"
        
        return True, "Dependencias Wine requeridas instaladas correctamente"

    def _install_verb(self, verb: str, progress_callback: Optional[Callable] = None, 
                      allow_failure: bool = False) -> Tuple[bool, str]:
        """Instala un verb de winetricks."""
        if not self.winetricks_path:
            return False, "winetricks no encontrado"

        if progress_callback:
            progress_callback(f"Instalando {verb}...")

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
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300, errors='replace')
            
            if result.returncode != 0:
                msg = f"winetricks {verb} falló (código {result.returncode}): {result.stderr[-500:]}"
                if allow_failure:
                    return True, f"⚠ {verb} falló (opcional): {msg}"
                return False, msg
            
            return True, f"{verb} OK"
        except subprocess.TimeoutExpired:
            msg = f"Timeout instalando {verb} (5 min)"
            if allow_failure:
                return True, f"⚠ {verb} timeout (opcional)"
            return False, msg
        except Exception as e:
            msg = f"Error con {verb}: {e}"
            if allow_failure:
                return True, f"⚠ {verb} error (opcional): {e}"
            return False, msg