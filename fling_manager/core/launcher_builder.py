from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import os
import shutil

from .icon_extractor import IconExtractor


class LauncherBuilder:
    """Genera scripts de lanzamiento y archivos .desktop para trainers."""

    def __init__(self, templates_dir: Path):
        self.templates_dir = Path(templates_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.icon_extractor = IconExtractor()

    def extract_trainer_icon(self, trainer_path: str, trainer_name: str) -> str:
        """
        Extrae el icono del trainer.exe.
        Retorna la ruta del icono o una cadena vacía si falla (usará fallback genérico).
        """
        success, result = self.icon_extractor.extract_icon(trainer_path, trainer_name)
        if success:
            return result
        # Fallback: icono genérico (vacío para que el template use fallback)
        return ""

    def copy_trainer_to_prefix(self, trainer_path: str, prefix_path: str) -> Tuple[bool, str]:
        """Copia el trainer al prefix del juego en C:\\Trainers\\"""
        try:
            trainer_src = Path(trainer_path)
            if not trainer_src.exists():
                return False, f"Trainer no encontrado: {trainer_path}"
            
            # Directorio destino en el prefix
            prefix_drive_c = Path(prefix_path) / "drive_c"
            trainers_dir = prefix_drive_c / "Trainers"
            trainers_dir.mkdir(parents=True, exist_ok=True)
            
            # Nombre sanitizado para Windows
            trainer_name = trainer_src.stem.replace(' ', '_').replace('(', '').replace(')', '')
            trainer_dst = trainers_dir / f"{trainer_name}.exe"
            
            # Copiar
            shutil.copy2(trainer_src, trainer_dst)
            
            # Retornar ruta Windows para usar en el script
            windows_path = f"C:\\\\Trainers\\\\{trainer_name}.exe"
            return True, windows_path
        except Exception as e:
            return False, f"Error copiando trainer al prefix: {e}"

    def build_launcher_script(self, game_data: Dict[str, Any], trainer_windows_path: str,
                              output_path: Path) -> bool:
        """Genera script .sh ejecutable para el trainer."""
        try:
            print(f"[DEBUG] build_launcher_script: trainer_windows_path={trainer_windows_path}")
            template = self.env.get_template('trainer_launcher.sh.j2')
            script_content = template.render(**game_data, trainer_path=trainer_windows_path)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(script_content)
            output_path.chmod(0o755)
            return True
        except Exception as e:
            print(f"Error generando launcher script: {e}")
            import traceback
            traceback.print_exc()
            return False

    def build_desktop_entry(self, game_data: Dict[str, Any],
                            script_path: Path,
                            icon_path: Optional[str] = None,
                            output_path: Path = None) -> bool:
        """Genera archivo .desktop para el menú de aplicaciones."""
        try:
            print(f"[DEBUG] build_desktop_entry: script_path={script_path}, icon_path={icon_path}")
            template = self.env.get_template('trainer.desktop.j2')
            # Evitar conflicto con game_data['icon_path'] - pasar como variable separada
            template_data = {**game_data}
            template_data.pop('icon_path', None)  # Remover si existe para evitar conflicto
            desktop_content = template.render(
                **template_data,
                script_path=str(script_path),
                icon_path=icon_path or "",
            )

            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(desktop_content)
            return True
        except Exception as e:
            print(f"Error generando .desktop: {e}")
            import traceback
            traceback.print_exc()
            return False

    def build_both(self, game_data: Dict[str, Any], trainer_path: str,
                   scripts_dir: Path, desktop_dir: Path,
                   icon_path: Optional[str] = None,
                   prefix_path: Optional[str] = None,
                   trainer_prefix_path: Optional[str] = None) -> Tuple[bool, str, str]:
        """Genera tanto script .sh como .desktop. Copia trainer al prefix."""
        # Sanitize game_id for filename
        safe_id = game_data['id'].replace('/', '_').replace(' ', '_')

        script_path = scripts_dir / f"fling-{safe_id}.sh"
        desktop_path = desktop_dir / f"fling-{safe_id}.desktop"

        # Determinar qué prefix usar para el trainer
        # trainer_prefix_path tiene prioridad sobre prefix_path
        effective_trainer_prefix = trainer_prefix_path or prefix_path

        # Copiar trainer al prefix si se proporciona
        trainer_windows_path = ""
        if effective_trainer_prefix:
            success, result = self.copy_trainer_to_prefix(trainer_path, effective_trainer_prefix)
            if not success:
                print(f"Error copiando trainer: {result}")
                return False, "", ""
            trainer_windows_path = result
        else:
            # Fallback: usar ruta Z: (legacy)
            trainer_windows_path = f"Z:{trainer_path}"

        # Extraer icono del trainer si no se proporcionó uno
        if not icon_path:
            trainer_name = Path(trainer_path).stem
            icon_path = self.extract_trainer_icon(trainer_path, trainer_name)

        # Preparar game_data para el template - usar el prefix del trainer para WINEPREFIX
        template_data = {**game_data}
        if trainer_prefix_path:
            # Sobrescribir prefix_path y compatdata_path para el trainer
            template_data['prefix_path'] = trainer_prefix_path
            template_data['compatdata_path'] = str(Path(trainer_prefix_path).parent)

        script_ok = self.build_launcher_script(template_data, trainer_windows_path, script_path)
        desktop_ok = self.build_desktop_entry(template_data, script_path, icon_path, desktop_path)

        return script_ok and desktop_ok, str(script_path), str(desktop_path)


def create_default_templates(templates_dir: Path):
    """Crea templates por defecto si no existen."""
    templates_dir.mkdir(parents=True, exist_ok=True)

    # trainer_launcher.sh.j2
    launcher_template = '''#!/usr/bin/env bash
# Auto-generado por Fling Trainer Manager
# Juego: {{ name }} ({{ launcher }})
# Trainer: {{ trainer_path }}

set -euo pipefail

GAME_ID="{{ app_id }}"
PREFIX="{{ prefix_path }}"
PROTON="{{ proton_path }}"
TRAINER="{{ trainer_path }}"

# Variables de entorno Steam/Proton
export STEAM_COMPAT_APP_ID="{{ app_id }}"
export STEAM_COMPAT_DATA_PATH="{{ compatdata_path }}"
export STEAM_COMPAT_CLIENT_INSTALL_PATH="{{ steam_install_path }}"
export STEAM_COMPAT_INSTALL_PATH="{{ install_path }}"
export STEAM_COMPAT_MEDIA_PATH="{{ compatdata_path }}/reports"
export WINEPREFIX="{{ prefix_path }}"
export MANGOHUD=0
export DWM_DISABLE=1
export WINEDEBUG=-all

# Matar wineserver previo para evitar version mismatch
pkill -9 wineserver 2>/dev/null || true
sleep 1

# Ejecutar trainer con EL MISMO Proton que el juego
exec "{{ proton_path }}" run "{{ trainer_path }}"
'''
    (templates_dir / "trainer_launcher.sh.j2").write_text(launcher_template)

    # trainer.desktop.j2
    desktop_template = '''[Desktop Entry]
Version=1.0
Type=Application
Name=Fling Trainer - {{ name }}
Comment=Fling Trainer para {{ name }}
Exec={{ script_path }}
Icon={{ icon_path }}
Terminal=false
Categories=Game;
StartupNotify=true
StartupWMClass=fling-trainer-{{ app_id }}
'''
    (templates_dir / "trainer.desktop.j2").write_text(desktop_template)