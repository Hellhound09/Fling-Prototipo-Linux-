import traceback
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from typing import Optional, List, Dict, Any
from pathlib import Path
import threading
import json
from datetime import datetime

from fling_manager.core.game_model import Game, TrainerConfig
from fling_manager.core.detectors import GameDetectorManager
from fling_manager.core.prefix_manager import PrefixManager, SudoHelper
from fling_manager.core.launcher_builder import LauncherBuilder, create_default_templates
from fling_manager.core.detectors import SteamDetector, LutrisDetector, HeroicDetector, LegendaryDetector, BottlesDetector, PortProtonDetector
from fling_manager.core.dotnet.detector import DotNetDetector
from fling_manager.config.settings import ConfigManager
from fling_manager.gui.widgets import GameComboBox, TrainerFilePicker, LogView, ProgressDialog


class MainWindow:
    """Ventana principal del Fling Trainer Manager."""

    def __init__(self, root: tb.Window):
        self.root = root
        self.root.title("Fling Trainer Manager")
        self.root.geometry("1000x700")
        self.root.minsize(900, 600)

        # Managers
        self.config = ConfigManager()
        self.detector_manager = GameDetectorManager()
        self.config_manager = self.config
        self.launcher_builder = None
        self.current_game: Optional[Game] = None
        self.current_trainer_path: Optional[str] = None

        # Variables UI
        self.detected_launchers: Dict[str, Any] = {}
        all_games = self.detector_manager.get_all_games()
        self.all_games = all_games

        # Inicializar templates
        templates_dir = Path(__file__).parent / "templates"
        create_default_templates(templates_dir)
        self.launcher_builder = LauncherBuilder(templates_dir)

        # Setup UI
        self._setup_style()
        self._create_menu()
        self._create_widgets()
        self._layout_widgets()

        # Cargar datos iniciales
        self._refresh_games()

        # Bindings
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_style(self):
        style = tb.Style()
        theme = self.config.get("theme", "darkly")
        try:
            style.theme_use(theme)
        except Exception:
            style.theme_use("darkly")

    def _create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Archivo
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Archivo", menu=file_menu)
        file_menu.add_command(label="Configuración", command=self._show_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self._on_close)

        # Herramientas
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Herramientas", menu=tools_menu)
        tools_menu.add_command(label="Actualizar lista de juegos", command=self._refresh_games)
        tools_menu.add_command(label="Instalar dependencias sistema", command=self._install_system_deps)
        tools_menu.add_separator()
        tools_menu.add_command(label="Limpiar caché iconos", command=self._clear_icon_cache)
        tools_menu.add_command(label="Eliminar Lanzador", command=self._delete_launcher)

        # Ayuda
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Ayuda", menu=help_menu)
        help_menu.add_command(label="Acerca de", command=self._show_about)

    def _create_widgets(self):
        # Frame principal con padding
        self.main_frame = ttk.Frame(self.root, padding=15)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # ===== SECCIÓN: SELECCIÓN DE JUEGO =====
        game_section = ttk.LabelFrame(self.main_frame, text="🎮 Juego", padding=10)
        self.game_combo = GameComboBox(
            game_section,
            games=[g.to_dict() for g in self.all_games],
            on_select=self._on_game_selected,
            width=60
        )
        self.game_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.refresh_btn = tb.Button(
            game_section, text="🔄 Actualizar", command=self._refresh_games,
            bootstyle="secondary-outline", width=15
        )
        self.refresh_btn.pack(side=tk.LEFT)

        # ===== SECCIÓN: TRAINER =====
        trainer_section = ttk.LabelFrame(self.main_frame, text="🎯 Trainer", padding=10)
        self.trainer_picker = TrainerFilePicker(
            trainer_section,
            on_change=self._on_trainer_changed
        )
        self.trainer_picker.pack(fill=tk.X)

        # ===== SECCIÓN: CONFIGURACIÓN DETECTADA =====
        config_section = ttk.LabelFrame(self.main_frame, text="⚙️ Configuración Detectada", padding=10)

        # Grid para info
        self.info_labels = {}
        info_fields = [
            ("Launcher", "launcher"),
            ("Prefijo Wine", "prefix_path"),
            ("Proton/Wine", "proton_path"),
            ("Ejecutable", "exe_name"),
            ("Ruta Juego", "install_path"),
        ]

        for i, (label, key) in enumerate(info_fields):
            ttk.Label(config_section, text=f"{label}:", font=("Sans", 9, "bold")).grid(
                row=i, column=0, sticky=tk.W, padx=(0, 10), pady=2
            )
            val_label = ttk.Label(config_section, text="—", font=("Sans", 9), foreground="#9cdcfe")
            val_label.grid(row=i, column=1, sticky=tk.W, pady=2)
            self.info_labels[key] = val_label

        # ===== BOTONES DE ACCIÓN =====
        action_frame = ttk.Frame(self.main_frame)
        action_frame.pack(fill=tk.X, pady=(15, 0))

        self.install_deps_btn = tb.Button(
            action_frame, text="🔧 Instalar .NET 4.8 + VC++ + d3dx",
            command=self._install_deps, bootstyle="warning", width=35
        )
        self.install_deps_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.create_launcher_btn = tb.Button(
            action_frame, text="🚀 Crear Lanzador",
            command=self._create_launcher, bootstyle="info", width=20
        )
        self.create_launcher_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.launch_btn = tb.Button(
            action_frame, text="▶ Lanzar Trainer",
            command=self._launch_trainer, bootstyle="success", width=20
        )
        self.launch_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.delete_launcher_btn = tb.Button(
            action_frame, text="🗑️ Eliminar Lanzador",
            command=self._delete_launcher, bootstyle="danger", width=20
        )
        self.delete_launcher_btn.pack(side=tk.LEFT)

        # ===== LOG VIEW =====
        log_section = ttk.LabelFrame(self.main_frame, text="📋 Registro", padding=10)
        self.log_view = LogView(log_section, height=150)
        self.log_view.pack(fill=tk.BOTH, expand=True)

        # Guardar referencias de secciones para mostrar/ocultar
        self.sections = {
            'game': game_section,
            'trainer': trainer_section,
            'config': config_section,
            'actions': action_frame,
            'log': log_section,
        }

    def _layout_widgets(self):
        # Usar pack para layout principal (evita conflictos pack/grid)
        self.sections['game'].pack(fill=tk.X, pady=(0, 10))
        self.sections['trainer'].pack(fill=tk.X, pady=(0, 10))
        self.sections['config'].pack(fill=tk.X, pady=(0, 10))
        self.sections['actions'].pack(fill=tk.X, pady=(0, 10))
        self.sections['log'].pack(fill=tk.BOTH, expand=True, pady=(0, 0))

    # ===== CALLBACKS =====

    def _on_game_selected(self, game_data: Dict):
        """Callback cuando se selecciona un juego."""
        self.current_game = Game.from_dict(game_data)
        self._update_config_display()
        self._auto_fill_trainer()
        self.log(f"Juego seleccionado: {game_data['name']} ({game_data['launcher']})")

    def _on_trainer_changed(self, path: str):
        self.current_trainer_path = path
        self.log(f"Trainer seleccionado: {Path(path).name}")

    def _auto_fill_trainer(self):
        """Intenta auto-rellenar trainer desde configuración guardada."""
        if not self.current_game:
            return
        trainer = self.config.get_trainer(self.current_game.id)
        if trainer and Path(trainer['trainer_path']).exists():
            self.trainer_picker.set_path(trainer['trainer_path'])
            self.current_trainer_path = trainer['trainer_path']
            self.log(f"Trainer cargado de config: {trainer['trainer_name']}")

    def _update_config_display(self):
        """Actualiza labels de configuración detectada."""
        if not self.current_game:
            for label in self.info_labels.values():
                label.config(text="—")
            return

        g = self.current_game
        self.info_labels['launcher'].config(text=g.launcher.capitalize())
        self.info_labels['prefix_path'].config(text=g.prefix_path or "No detectado")
        self.info_labels['proton_path'].config(text=g.proton_path or "Auto-detectar")
        self.info_labels['exe_name'].config(text=g.exe_name or "No detectado")
        self.info_labels['install_path'].config(text=g.install_path or "No detectado")

    # ===== ACCIONES PRINCIPALES =====

    def _refresh_games(self):
        """Actualiza lista de juegos detectados."""
        self.log("🔄 Detectando juegos en Steam, Lutris, Heroic, Legendary, Bottles, PortProton...")
        self.refresh_btn.config(state=tk.DISABLED)

        def worker():
            try:
                launchers = self.detector_manager.detect_all()
                self.detected_launchers = launchers
                all_games = []
                for launcher_config in launchers.values():
                    all_games.extend(launcher_config.games)
                self.all_games = all_games

                # Actualizar UI en hilo principal
                self.root.after(0, lambda: self._update_game_list(all_games))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"❌ Error detectando juegos: {e}", "error"))
            finally:
                self.root.after(0, lambda: self.refresh_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    def _update_game_list(self, games: List[Game]):
        """Actualiza combo con nuevos juegos."""
        display_list = [g.to_dict() for g in games]
        self.game_combo.update_games(display_list)
        total = len(games)
        by_launcher = {}
        for g in games:
            by_launcher[g.launcher] = by_launcher.get(g.launcher, 0) + 1
        detail = ", ".join(f"{k}: {v}" for k, v in by_launcher.items())
        self.log(f"✅ Detectados {total} juegos ({detail})")

    def _on_trainer_changed(self, path: str):
        self.current_trainer_path = path
        self.log(f"📁 Trainer: {Path(path).name}")

    def _install_deps(self):
        """Instala dependencias completas en el prefijo del juego."""
        if not self.current_game:
            messagebox.showwarning("Sin juego", "Selecciona un juego primero")
            return

        if not self.current_game.prefix_path:
            messagebox.showwarning("Sin prefijo", "No se detectó prefijo Wine para este juego")
            return

        if not self.current_game.proton_path:
            messagebox.showwarning("Sin Proton", "No se detectó Proton para este juego")
            return

        # Verificar instalador .NET (auto-descarga si no existe)
        dotnet_installer = self.config.get_dotnet_installer()
        if not dotnet_installer or not Path(dotnet_installer).exists():
            # Preguntar si quiere auto-descargar
            if messagebox.askyesno(
                "Instalador .NET 4.8 no encontrado",
                "No se encontró el instalador de .NET 4.8.\n\n"
                "¿Desea descargarlo automáticamente desde Microsoft?\n"
                "(~116 MB, se guardará en carpeta temporal)"
            ):
                dotnet_installer = None  # Se auto-descargará en PrefixManager
                self.log("📥 Se descargará .NET 4.8 automáticamente desde Microsoft")
            else:
                # Permitir selección manual como fallback
                path = filedialog.askopenfilename(
                    title="Seleccionar instalador .NET 4.8 (NDP48-x86-x64-AllOS-ENU.exe)",
                    filetypes=[("Ejecutable", "*.exe"), ("Todos", "*.*")]
                )
                if not path:
                    return
                self.config.set_dotnet_installer(path)
                dotnet_installer = path

        # Crear ProgressDialog
        dialog = ProgressDialog(self.root, "Instalando dependencias")
        dialog.log(f"Juego: {self.current_game.name}")
        dialog.log(f"Prefijo: {self.current_game.prefix_path}")
        dialog.log(f"Proton: {self.current_game.proton_path}")

        def worker():
            try:
                prefix_mgr = PrefixManager(
                    self.current_game.prefix_path,
                    self.current_game.proton_path,
                    self.root
                )

                def progress_cb(msg):
                    self.root.after(0, lambda: dialog.update_status(msg))
                    self.root.after(0, lambda: dialog.log(msg, "info"))

                success, msg = prefix_mgr.install_full_profile(
                    dotnet_installer=dotnet_installer,
                    install_system_deps=self.config.get("install_system_deps", True),
                    progress_callback=progress_cb
                )
                self.root.after(0, lambda: dialog.finish(success, msg))
            except Exception as e:
                self.root.after(0, lambda: dialog.finish(False, f"Error: {e}"))

        threading.Thread(target=worker, daemon=True).start()
        dialog.wait()

    def _create_launcher(self):
        """Crea script .sh y .desktop para el trainer. Copia trainer al prefix."""
        if not self.current_game:
            messagebox.showwarning("Sin juego", "Selecciona un juego primero")
            return

        if not self.current_trainer_path:
            messagebox.showwarning("Sin trainer", "Selecciona el archivo .exe del trainer")
            return

        # Resolver ruta completa del trainer
        trainer_path = self._resolve_trainer_path(self.current_trainer_path)
        if not trainer_path:
            messagebox.showerror("Error", 
                f"No se encuentra el trainer: {self.current_trainer_path}\n"
                f"Verifica que el archivo existe y la ruta es correcta.")
            return

        # Preparar datos para template
        game_data = self.current_game.to_dict()
        game_data.update({
            'compatdata_path': str(Path(self.current_game.prefix_path).parent),
            'steam_install_path': self.config.get_steam_path(),
        })

        # Directorios de salida
        scripts_dir = Path.home() / ".local" / "bin"
        desktop_dir = Path.home() / ".local" / "share" / "applications"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        desktop_dir.mkdir(parents=True, exist_ok=True)

# Buscar icono (placeholder por ahora)
        icon_path = None

        try:
            self.log(f"📋 Creando lanzador para {self.current_game.name}...")
            self.log(f"   Trainer: {Path(trainer_path).name}")
            self.log(f"   Ruta completa: {trainer_path}")
            self.log(f"   Prefijo: {self.current_game.prefix_path}")
            
            # Buscar prefix alternativo con .NET funcional (automático)
            trainer_prefix = None
            if self.current_game.app_id == '2161700':  # Persona 3 Reload
                # Buscar prefix de Persona 5 Royal (1687950)
                for g in self.all_games:
                    if g.app_id == '1687950':
                        trainer_prefix = g.prefix_path
                        self.log(f"✅ Usando prefix de P5R para trainer: {trainer_prefix}")
                        break
            
            # Permitir que se use un prefix alternativo con .NET funcional
            if not trainer_prefix:
                # Run detection in background thread to avoid blocking UI
                def find_working_prefix():
                    for g in self.all_games:
                        if g.id != self.current_game.id and g.prefix_path:
                            detector = DotNetDetector(Path(g.prefix_path))
                            if detector.is_dotnet48_installed()[0]:
                                return g.prefix_path
                    return None
                
                # Run detection in background
                import threading
                result = {}
                def worker():
                    result['prefix'] = find_working_prefix()
                
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                thread.join(timeout=10.0)  # Wait max 10 seconds
                
                if 'prefix' in result and result['prefix']:
                    trainer_prefix = result['prefix']
                    self.log(f"✅ Usando prefix alternativo con .NET funcional: {trainer_prefix}")
            
            ok, script_path, desktop_path = self.launcher_builder.build_both(
                game_data, trainer_path, scripts_dir, desktop_dir, icon_path,
                prefix_path=self.current_game.prefix_path,
                trainer_prefix_path=trainer_prefix
            )
            if ok:
                # Guardar trainer en config (usar ruta resuelta)
                self.config.add_trainer(
                    self.current_game.id,
                    trainer_path,
                    Path(trainer_path).stem
                )
                self.log(f"✅ Lanzador creado: {script_path}")
                self.log(f"✅ Entrada .desktop: {desktop_path}")
                messagebox.showinfo(
                    "Éxito",
                    f"Lanzador creado correctamente:\n\n"
                    f"Script: {script_path}\n"
                    f"Desktop: {desktop_path}\n\n"
                    f"El trainer se copió al prefix del juego.\n"
                    f"Ahora puedes buscar 'Fling Trainer - {self.current_game.name}' en tu menú de aplicaciones."
                )
            else:
                self.log("❌ Error creando lanzador (build_both returned False)", "error")
                messagebox.showerror("Error", "No se pudo crear el lanzador")
        except Exception as e:
            error_detail = traceback.format_exc()
            self.log(f"❌ Error creando lanzador: {e}", "error")
            self.log(error_detail, "debug")
            messagebox.showerror("Error", f"Error creando lanzador:\n{e}")

    def _delete_launcher(self):
        """Elimina el lanzador, el archivo .desktop y el trainer copiado en el prefix."""
        if not self.current_game:
            messagebox.showwarning("Sin juego", "Selecciona un juego primero")
            return

        # Confirmar eliminación
        if not messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Eliminar el lanzador y trainer copiado para '{self.current_game.name}'?\n\n"
            f"Esto eliminará:\n"
            f"  • Script: ~/.local/bin/fling-{self.current_game.id.replace('/', '_').replace(' ', '_')}.sh\n"
            f"  • Desktop: ~/.local/share/applications/fling-{self.current_game.id.replace('/', '_').replace(' ', '_')}.desktop\n"
            f"  • Trainer copiado en: {self.current_game.prefix_path}/drive_c/Trainers/ (si existe)",
            icon=messagebox.WARNING
        ):
            return

        safe_id = self.current_game.id.replace('/', '_').replace(' ', '_')
        
        # 1. Eliminar script .sh
        script_path = Path.home() / ".local" / "bin" / f"fling-{safe_id}.sh"
        if script_path.exists():
            try:
                script_path.unlink()
                self.log(f"✅ Script eliminado: {script_path}")
            except Exception as e:
                self.log(f"⚠ Error eliminando script: {e}", "warning")

        # 2. Eliminar archivo .desktop
        desktop_path = Path.home() / ".local" / "share" / "applications" / f"fling-{safe_id}.desktop"
        if desktop_path.exists():
            try:
                desktop_path.unlink()
                self.log(f"✅ Entrada .desktop eliminada: {desktop_path}")
            except Exception as e:
                self.log(f"⚠ Error eliminando .desktop: {e}", "warning")

        # 3. Eliminar trainer copiado en el prefix del juego
        if self.current_game.prefix_path:
            trainer_name = Path(self.current_trainer_path).stem.replace(' ', '_').replace('(', '').replace(')', '') if self.current_trainer_path else ""
            if trainer_name:
                trainer_path_in_prefix = Path(self.current_game.prefix_path) / "drive_c" / "Trainers" / f"{trainer_name}.exe"
                if trainer_path_in_prefix.exists():
                    try:
                        trainer_path_in_prefix.unlink()
                        self.log(f"✅ Trainer copiado eliminado: {trainer_path_in_prefix}")
                    except Exception as e:
                        self.log(f"⚠ Error eliminando trainer copiado: {e}", "warning")

        # 4. Eliminar de config
        self.config.remove_trainer(self.current_game.id)
        self.log(f"✅ Configuración de trainer eliminada")

        # 5. Limpiar icono extraído si existe
        if self.current_trainer_path:
            trainer_name = Path(self.current_trainer_path).stem.replace(' ', '_').replace('(', '').replace(')', '')
            icon_dir = Path.home() / ".local" / "share" / "fling-trainer-manager" / "icons" / trainer_name
            if icon_dir.exists():
                try:
                    import shutil
                    shutil.rmtree(icon_dir)
                    self.log(f"✅ Directorio de iconos eliminado: {icon_dir}")
                except Exception as e:
                    self.log(f"⚠ Error eliminando iconos: {e}", "warning")

        self.log(f"✅ Lanzador y archivos asociados eliminados para {self.current_game.name}")
        messagebox.showinfo("Eliminado", f"Lanzador y archivos de '{self.current_game.name}' eliminados correctamente.")

    def _resolve_trainer_path(self, path: str) -> Optional[str]:
        """Resuelve la ruta completa del trainer si es relativa o solo nombre."""
        p = Path(path)
        if p.is_absolute() and p.exists():
            self.log(f"✅ Trainer path resuelto (absoluto): {p}")
            return str(p)
        
        # Si es relativo, buscar en ubicaciones comunes
        search_dirs = [
            Path.cwd(),
            Path.home() / "Descargas",
            Path.home() / "Downloads",
            Path.home() / "Trainers",
            Path("/run/media/david/HDD 500GB/Descargas"),
            Path("/run/media/david/HDD 1TB/Descargas"),
        ]
        
        for base in search_dirs:
            candidate = base / path
            if candidate.exists():
                self.log(f"✅ Trainer path resuelto (relativo): {candidate}")
                return str(candidate)
            # Buscar por nombre en el directorio
            if base.exists():
                for f in base.glob(f"*{p.name}*"):
                    if f.is_file() and f.suffix.lower() == '.exe':
                        self.log(f"✅ Trainer path encontrado por nombre: {f}")
                        return str(f)
        
        self.log(f"❌ No se pudo resolver trainer path: {path}", "error")
        return None

    def _launch_trainer(self):
        """Lanza el trainer usando el script generado con setsid/nohup para desacoplar correctamente."""
        if not self.current_game:
            messagebox.showwarning("Sin juego", "Selecciona un juego primero")
            return

        if not self.current_trainer_path:
            messagebox.showwarning("Sin trainer", "Selecciona el archivo .exe del trainer")
            return

        # Resolver ruta completa del trainer
        trainer_path = self._resolve_trainer_path(self.current_trainer_path)
        if not trainer_path:
            messagebox.showerror("Error", 
                f"No se encuentra el trainer: {self.current_trainer_path}")
            return

        # Buscar script generado
        safe_id = self.current_game.id.replace('/', '_').replace(' ', '_')
        script_path = Path.home() / ".local" / "bin" / f"fling-{safe_id}.sh"
        
        if not script_path.exists():
            self.log(f"⚠ Script no encontrado: {script_path}. Creando lanzador primero...", "warning")
            self._create_launcher()
            if not script_path.exists():
                messagebox.showerror("Error", "No se pudo crear el lanzador")
                return

        self.log(f"🚀 Lanzando trainer para {self.current_game.name}...")
        self.log(f"   Usando script: {script_path}")

        def worker():
            try:
                # Usar setsid + nohup para desacoplar correctamente el proceso
                # Esto evita problemas con PTY que interfieren con Wine/Proton
                cmd = ['setsid', 'nohup', str(script_path)]
                
                # Lanzar completamente desacoplado
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                
                self.root.after(0, lambda: self.log(f"✅ Trainer lanzado (PID: {proc.pid})", "success"))
                # Verificar que sigue corriendo después de 2 seg
                def check_proc():
                    import time
                    time.sleep(2)
                    if proc.poll() is None:
                        self.root.after(0, lambda: self.log("✅ Trainer ejecutándose correctamente", "success"))
                    else:
                        self.root.after(0, lambda: self.log(f"⚠ Trainer terminó con código {proc.returncode()}", "warning"))
                
                threading.Thread(target=check_proc, daemon=True).start()
                
            except Exception as e:
                self.root.after(0, lambda: self.log(f"❌ Error lanzando trainer: {e}", "error"))

        threading.Thread(target=worker, daemon=True).start()

    def _install_system_deps(self):
        """Instala solo dependencias de sistema 32-bit."""
        if not self.current_game:
            messagebox.showwarning("Sin juego", "Selecciona un juego primero")
            return

        if not self.current_game.proton_path:
            messagebox.showwarning("Sin Proton", "No se detectó Proton")
            return

        dialog = ProgressDialog(self.root, "Instalando dependencias 32-bit")

        def worker():
            try:
                prefix_mgr = PrefixManager(
                    self.current_game.prefix_path,
                    self.current_game.proton_path,
                    self.root
                )

                def progress_cb(msg):
                    self.root.after(0, lambda: dialog.update_status(msg))
                    self.root.after(0, lambda: dialog.log(msg, "info"))

                success, msg = prefix_mgr.install_system_deps_32bit(progress_cb)
                self.root.after(0, lambda: dialog.finish(success, msg))
            except Exception as e:
                self.root.after(0, lambda: dialog.finish(False, f"Error: {e}"))

        threading.Thread(target=worker, daemon=True).start()
        dialog.wait()

    # ===== MENÚ Y UTILIDADES =====

    def _show_settings(self):
        """Ventana de configuración."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Configuración")
        dialog.geometry("500x450")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # Centrar
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() // 2) - 250
        y = self.root.winfo_rooty() + (self.root.winfo_height() // 2) - 225
        dialog.geometry(f"500x450+{x}+{y}")

        notebook = ttk.Notebook(dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Pestaña Rutas ---
        paths_frame = ttk.Frame(notebook, padding=15)
        notebook.add(paths_frame, text="Rutas")

        # Steam path
        ttk.Label(paths_frame, text="Ruta Steam:").grid(row=0, column=0, sticky=tk.W, pady=5)
        steam_var = tk.StringVar(value=self.config.get_steam_path())
        ttk.Entry(paths_frame, textvariable=steam_var, width=50).grid(row=0, column=1, padx=5)
        tb.Button(paths_frame, text="📁", command=lambda: self._browse_path(steam_var)).grid(row=0, column=2)

        # .NET installer
        ttk.Label(paths_frame, text="Instalador .NET 4.8:").grid(row=1, column=0, sticky=tk.W, pady=5)
        dotnet_var = tk.StringVar(value=self.config.get_dotnet_installer())
        ttk.Entry(paths_frame, textvariable=dotnet_var, width=50).grid(row=1, column=1, padx=5)
        tb.Button(paths_frame, text="📁", command=lambda: self._browse_file(dotnet_var, "Ejecutables (*.exe)")).grid(row=1, column=2)

        # SteamGridDB API Key
        ttk.Label(paths_frame, text="SteamGridDB API Key:").grid(row=2, column=0, sticky=tk.W, pady=5)
        api_var = tk.StringVar(value=self.config.get_steamgrid_api_key())
        ttk.Entry(paths_frame, textvariable=api_var, width=50, show="*").grid(row=2, column=1, padx=5)

        # --- Pestaña Opciones ---
        options_frame = ttk.Frame(notebook, padding=15)
        notebook.add(options_frame, text="Opciones")

        install_sys_var = tk.BooleanVar(value=self.config.get("install_system_deps", True))
        ttk.Checkbutton(options_frame, text="Instalar dependencias de sistema (32-bit) automáticamente",
                       variable=install_sys_var, bootstyle="round-toggle").pack(anchor=tk.W, pady=10)

        auto_deps_var = tk.BooleanVar(value=self.config.get("auto_install_deps", True))
        ttk.Checkbutton(options_frame, text="Instalar dependencias Wine (.NET, vcrun, d3dx) automáticamente",
                       variable=auto_deps_var, bootstyle="round-toggle").pack(anchor=tk.W, pady=10)

        # Theme
        ttk.Label(options_frame, text="Tema:").pack(anchor=tk.W, pady=(15, 0))
        theme_var = tk.StringVar(value=self.config.get("theme", "darkly"))
        theme_combo = ttk.Combobox(options_frame, textvariable=theme_var,
                                   values=["darkly", "cosmo", "flatly", "litera", "minty", "pulse", "sandstone", "yeti"],
                                   state="readonly", width=20)
        theme_combo.pack(anchor=tk.W, pady=5)

        # --- Botones ---
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=15, pady=15)

        def save_settings():
            self.config.set_steam_path(steam_var.get())
            self.config.set_dotnet_installer(dotnet_var.get())
            self.config.set_steamgrid_api_key(api_var.get())
            self.config.set("install_system_deps", install_sys_var.get())
            self.config.set("auto_install_deps", auto_deps_var.get())
            self.config.set("theme", theme_var.get())
            messagebox.showinfo("Guardado", "Configuración guardada. Reinicia la app para aplicar tema.")
            dialog.destroy()

        tb.Button(btn_frame, text="Guardar", command=save_settings, bootstyle="success").pack(side=tk.RIGHT, padx=5)
        tb.Button(btn_frame, text="Cancelar", command=dialog.destroy, bootstyle="secondary").pack(side=tk.RIGHT)

    def _browse_path(self, var: tk.StringVar):
        path = filedialog.askdirectory(title="Seleccionar directorio")
        if path:
            var.set(path)

    def _browse_file(self, var: tk.StringVar, filetypes: str):
        path = filedialog.askopenfilename(title="Seleccionar archivo", filetypes=[(filetypes, "*.exe"), ("Todos", "*.*")])
        if path:
            var.set(path)

    def _clear_icon_cache(self):
        self.config.clear_cache()
        self.log("🗑️ Caché de iconos limpiada")
        messagebox.showinfo("Listo", "Caché de iconos limpiada")

    def _show_about(self):
        messagebox.showinfo(
            "Acerca de Fling Trainer Manager",
            "Fling Trainer Manager v1.0\n\n"
            "Gestor gráfico para trainers de Fling en Linux.\n"
            "Compatible con Steam, Lutris, Heroic, Legendary, Bottles y PortProton.\n\n"
            "Desarrollado para CachyOS / Arch Linux"
        )

    def _on_close(self):
        # Guardar geometría ventana
        geom = self.root.geometry()
        self.config.set("window_geometry", geom)
        self.root.destroy()

    def log(self, message: str, level: str = "info"):
        """Log thread-safe."""
        self.root.after(0, lambda: self.log_view.log(message, level))

    def run(self):
        self.root.mainloop()


def main():
    """Punto de entrada principal."""
    root = tb.Window(themename="darkly")
    app = MainWindow(root)
    app.run()


if __name__ == "__main__":
    main()