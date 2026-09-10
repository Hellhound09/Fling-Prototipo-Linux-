from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import os
import shutil

from .icon_extractor import IconExtractor


class LauncherBuilder:
    """Genera archivos .desktop para trainers. La ejecución se maneja via ProtonLauncher."""

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
        return ""

    def copy_trainer_to_prefix(self, trainer_path: str, prefix_path: str) -> Tuple[bool, str]:
        """Copia el trainer al prefix del juego en C:\\Trainers\\"""
        try:
            trainer_src = Path(trainer_path)
            if not trainer_src.exists():
                return False, f"Trainer no encontrado: {trainer_path}"

            prefix_drive_c = Path(prefix_path) / "drive_c"
            trainers_dir = prefix_drive_c / "Trainers"
            trainers_dir.mkdir(parents=True, exist_ok=True)

            trainer_name = trainer_src.stem.replace(' ', '_').replace('(', '').replace(')', '')
            trainer_dst = trainers_dir / f"{trainer_name}.exe"

            shutil.copy2(trainer_src, trainer_dst)

            windows_path = f"C:\\\\Trainers\\\\{trainer_name}.exe"
            return True, windows_path
        except Exception as e:
            return False, f"Error copiando trainer al prefix: {e}"

    def build_desktop_entry(self, game_data: Dict[str, Any],
                            script_path: Path,
                            icon_path: Optional[str] = None,
                            output_path: Path = None) -> bool:
        """Genera archivo .desktop para el menú de aplicaciones.
        script_path: path al script Python que lanza el trainer (no usado directamente, para compatibilidad)
        """
        try:
            template = self.env.get_template('trainer.desktop.j2')
            template_data = {**game_data}
            template_data.pop('icon_path', None)
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

    def create_launcher_files(self, game_data: Dict[str, Any], trainer_path: str,
                              scripts_dir: Path, desktop_dir: Path,
                              icon_path: Optional[str] = None,
                              prefix_path: Optional[str] = None,
                              trainer_prefix_path: Optional[str] = None) -> Tuple[bool, str, str]:
        """Copia trainer al prefix y genera .desktop entry.
        Retorna: (success, trainer_windows_path, desktop_path)
        """
        safe_id = game_data['id'].replace('/', '_').replace(' ', '_')
        desktop_path = desktop_dir / f"fling-{safe_id}.desktop"

        effective_trainer_prefix = trainer_prefix_path or prefix_path
        trainer_windows_path = ""

        if effective_trainer_prefix:
            success, result = self.copy_trainer_to_prefix(trainer_path, effective_trainer_prefix)
            if not success:
                print(f"Error copiando trainer: {result}")
                return False, "", ""
            trainer_windows_path = result
        else:
            trainer_windows_path = f"Z:{trainer_path}"

        if not icon_path:
            trainer_name = Path(trainer_path).stem
            icon_path = self.extract_trainer_icon(trainer_path, trainer_name)

        template_data = {**game_data}
        template_data['trainer_path'] = trainer_windows_path
        if trainer_prefix_path:
            template_data['prefix_path'] = trainer_prefix_path
            template_data['compatdata_path'] = str(Path(trainer_prefix_path).parent)

        desktop_ok = self.build_desktop_entry(template_data, Path(""), icon_path, desktop_path)

        return desktop_ok, trainer_windows_path, str(desktop_path)


def create_default_templates(templates_dir: Path):
    """Crea templates por defecto si no existen (solo .desktop)."""
    templates_dir.mkdir(parents=True, exist_ok=True)

    desktop_template = '''[Desktop Entry]
Version=1.0
Type=Application
Name=Fling Trainer - {{ name }}
Comment=Fling Trainer para {{ name }}
Exec=python3 -m fling_manager.core.proton_launcher {{ id }} "{{ trainer_path }}"
Icon={{ icon_path }}
Terminal=false
Categories=Game;
StartupNotify=true
StartupWMClass=fling-trainer-{{ app_id }}
'''
    (templates_dir / "trainer.desktop.j2").write_text(desktop_template)