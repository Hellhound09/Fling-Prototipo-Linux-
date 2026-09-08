"""Extractor de iconos de archivos .exe usando 7z o wrestool."""

import subprocess
import os
import logging
from pathlib import Path
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


class IconExtractor:
    """Extrae iconos de archivos .exe usando 7z o wrestool."""

    def __init__(self, icons_dir: Optional[Path] = None):
        self.icons_dir = icons_dir or Path.home() / ".local" / "share" / "fling-trainer-manager" / "icons"
        self.icons_dir.mkdir(parents=True, exist_ok=True)

    def _find_7z(self) -> Optional[Path]:
        """Busca 7z en el sistema."""
        candidates = [
            Path("/usr/bin/7z"),
            Path("/usr/bin/7zz"),
            Path("/usr/bin/7za"),
            Path("/usr/local/bin/7z"),
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _find_wrestool(self) -> Optional[Path]:
        """Busca wrestool (icoutils) en el sistema."""
        candidates = [
            Path("/usr/bin/wrestool"),
            Path("/usr/local/bin/wrestool"),
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def extract_icon_7z(self, exe_path: Path, output_name: str) -> Tuple[bool, str]:
        """
        Extrae icono usando 7z.
        Retorna (success, icon_path_or_error).
        """
        seven_z = self._find_7z()
        if not seven_z:
            return False, "7z no encontrado en el sistema"

        try:
            output_dir = self.icons_dir / output_name
            output_dir.mkdir(parents=True, exist_ok=True)

            # 7z puede extraer recursos del .exe
            # Primero listar recursos para encontrar iconos
            list_cmd = [str(seven_z), 'l', str(exe_path)]
            result = subprocess.run(list_cmd, capture_output=True, text=True, timeout=30, errors='replace')
            
            if result.returncode != 0:
                return False, f"7z no puede leer el archivo: {result.stderr}"

            # Extraer todos los recursos
            extract_cmd = [
                str(seven_z), 'x', str(exe_path),
                f'-o{output_dir}',
                '-y'
            ]
            result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=60, errors='replace')
            
            if result.returncode != 0:
                return False, f"Error extrayendo con 7z: {result.stderr}"

            # Buscar archivos .ico en la salida
            ico_files = list(output_dir.rglob("*.ico"))
            if not ico_files:
                # Buscar también archivos de imagen que podrían ser iconos
                for ext in ['.png', '.bmp']:
                    ico_files = list(output_dir.rglob(f"*{ext}"))
                    if ico_files:
                        break
            
            if not ico_files:
                return False, "No se encontraron iconos en el ejecutable"

            # Seleccionar el icono más grande (probablemente el principal)
            best_ico = max(ico_files, key=lambda f: f.stat().st_size)
            
            # Copiar a ubicación final con nombre limpio
            final_path = self.icons_dir / f"{Path(ico_files[0]).stem}.ico" if ico_files[0].suffix == '.ico' else self.icons_dir / f"{output_name}.png"
            
            # Si es .ico, copiar como .ico; si es png/bmp, convertir o copiar
            import shutil
            shutil.copy2(best_ico, final_path)
            
            return True, str(final_path)

        except subprocess.TimeoutExpired:
            return False, "Timeout extrayendo icono (30s)"
        except Exception as e:
            return False, f"Error extrayendo icono: {e}"

    def extract_icon_wrestool(self, exe_path: Path, output_name: str) -> Tuple[bool, str]:
        """
        Extrae icono usando wrestool (icoutils) - más específico para recursos Windows.
        """
        wrestool = self._find_wrestool()
        if not wrestool:
            return False, "wrestool no encontrado en el sistema"

        try:
            output_dir = self.icons_dir / output_name
            output_dir.mkdir(parents=True, exist_ok=True)

            # wrestool -x extrae recursos, --type=14 es RT_GROUP_ICON
            cmd = [
                str(wrestool), '-x', '--type=14',
                '--output', str(output_dir),
                str(exe_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, errors='replace')
            
            if result.returncode != 0:
                # Intentar sin filtro de tipo
                cmd = [str(wrestool), '-x', '--output', str(output_dir), str(exe_path)]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, errors='replace')
                if result.returncode != 0:
                    return False, f"wrestool falló: {result.stderr}"

            # Buscar archivos .ico
            ico_files = list(output_dir.rglob("*.ico"))
            if not ico_files:
                return False, "No se encontraron iconos con wrestool"

            best_ico = max(ico_files, key=lambda f: f.stat().st_size)
            final_path = self.icons_dir / f"{output_name}.ico"
            
            import shutil
            shutil.copy2(best_ico, final_path)
            
            return True, str(final_path)

        except subprocess.TimeoutExpired:
            return False, "Timeout extrayendo icono (60s)"
        except Exception as e:
            return False, f"Error extrayendo icono con wrestool: {e}"

    def extract_icon(self, exe_path: str, trainer_name: str) -> Tuple[bool, str]:
        """
        Intenta extraer icono usando el mejor método disponible.
        Primero wrestool (más específico), luego 7z como fallback.
        """
        exe_path = Path(exe_path)
        if not exe_path.exists():
            return False, f"Archivo no encontrado: {exe_path}"

        # Sanitizar nombre para usar como directorio/salida
        safe_name = "".join(c for c in trainer_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')[:100]

        # Intentar wrestool primero (mejor para recursos Windows)
        wrestool = self._find_wrestool()
        if wrestool:
            success, result = self.extract_icon_wrestool(Path(exe_path), safe_name)
            if success:
                return True, result
            logger.warning(f"wrestool falló, probando 7z: {result}")

        # Fallback a 7z
        seven_z = self._find_7z()
        if seven_z:
            success, result = self.extract_icon_7z(Path(exe_path), safe_name)
            if success:
                return True, result
            logger.warning(f"7z también falló: {result}")

        return False, "No se pudo extraer icono con ninguna herramienta"

    def get_generic_icon(self) -> str:
        """Retorna ruta a icono genérico (crear uno si no existe)."""
        generic_path = self.icons_dir / "generic_trainer.png"
        if not generic_path.exists():
            # Crear un icono genérico simple usando ImageMagick o crear uno vacío
            # Por ahora retornamos una ruta vacía para que el template maneje fallback
            pass
        return str(generic_path) if generic_path.exists() else ""


def extract_trainer_icon(exe_path: str, trainer_name: str, icons_dir: Optional[Path] = None) -> Tuple[bool, str]:
    """
    Función de conveniencia para extraer icono de un trainer.
    Retorna (success, icon_path_or_error).
    """
    extractor = IconExtractor(icons_dir)
    return extractor.extract_icon(exe_path, trainer_name)