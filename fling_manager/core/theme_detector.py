"""Detección de tema del sistema (GTK3/GTK4 + Qt/KDE) con live reload."""

import os
import subprocess
import threading
import time
import configparser
from pathlib import Path
from typing import Optional, Callable, List
from dataclasses import dataclass


@dataclass
class SystemThemeInfo:
    """Información del tema del sistema detectado."""
    gtk_theme: str
    is_dark: bool
    color_scheme: str  # 'prefer-dark', 'prefer-light', 'default'
    qt_theme: Optional[str] = None
    desktop_env: str = ""


class ThemeDetector:
    """Detecta tema del sistema (GTK3/GTK4 + Qt/KDE) con live reload."""

    GTK3_SETTINGS = Path.home() / ".config" / "gtk-3.0" / "settings.ini"
    GTK4_SETTINGS = Path.home() / ".config" / "gtk-4.0" / "settings.ini"
    KDE_GLOBALS = Path.home() / ".config" / "kdeglobals"

    # Mapeo de temas GTK/Qt conocidos a temas ttkbootstrap
    GTK_TO_TTKBOOTSTRAP = {
        # Temas oscuros -> darkly
        "Adwaita-dark": "darkly",
        "Adwaita:dark": "darkly",
        "Breeze-Dark": "darkly",
        "Breeze-Dark-GTK": "darkly",
        "Yaru-dark": "darkly",
        "Yaru-mate-dark": "darkly",
        "Pop-dark": "darkly",
        "ZorinBlue-Dark": "darkly",
        "Materia-dark": "darkly",
        "Materia-dark-compact": "darkly",
        "Arc-Dark": "darkly",
        "Arc-Darker": "darkly",
        "Nordic-darker": "darkly",
        "Canta-dark": "darkly",
        "Orchis-Dark": "darkly",
        "WhiteSur-Dark": "darkly",
        "Graphite-Dark": "darkly",
        "Adw-gtk3-dark": "darkly",
        "Breeze-Dark": "darkly",
        "Oxygen-Dark": "darkly",

        # Temas claros -> flatly/litera/cosmo
        "Adwaita": "flatly",
        "Adwaita:light": "flatly",
        "Breeze": "cosmo",
        "Breeze-Light": "cosmo",
        "Yaru": "litera",
        "Pop": "minty",
        "ZorinBlue-Light": "minty",
        "Materia": "minty",
        "Materia-light": "minty",
        "Arc": "litera",
        "Nordic": "litera",
        "Canta": "litera",
        "Orchis": "litera",
        "WhiteSur": "litera",
        "Graphite": "litera",
        "Adw-gtk3": "litera",

        # KDE/Qt
        "Breeze": "cosmo",
        "Oxygen": "cosmo",
    }

    DEFAULT_LIGHT = "flatly"
    DEFAULT_DARK = "darkly"

    def __init__(self):
        self._callbacks: List[Callable[[str], None]] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_theme: Optional[str] = None

    def detect_system_theme(self) -> SystemThemeInfo:
        """Detecta tema actual del sistema (GTK + Qt)."""
        # 1. Detectar desktop environment
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        xdg_desktop = os.environ.get("XDG_DESKTOP", "").lower()
        desktop_env = f"{desktop} {xdg_desktop}".lower()

        # 2. Leer configuración GTK3
        gtk_theme, gtk_dark = self._read_gtk_settings(self.GTK3_SETTINGS)
        if not gtk_theme:
            gtk_theme, gtk_dark = self._read_gtk_settings(self.GTK4_SETTINGS)

        # 3. Leer configuración Qt/KDE
        qt_theme, qt_dark = self._read_kde_globals()

        # 4. gsettings (GNOME)
        gsettings_theme, gsettings_scheme = self._get_gsettings()

        # 5. Determinar tema final
        theme_name = self._resolve_theme(
            gtk_theme, gtk_dark,
            qt_theme, qt_dark,
            gsettings_theme, gsettings_scheme,
            desktop_env
        )

        is_dark = self._is_dark_theme(theme_name, gtk_dark, gsettings_scheme)

        return SystemThemeInfo(
            gtk_theme=theme_name,
            is_dark=is_dark,
            color_scheme="prefer-dark" if is_dark else "prefer-light",
            qt_theme=qt_theme,
            desktop_env=desktop_env
        )

    def _read_gtk_settings(self, path: Path) -> tuple[Optional[str], bool]:
        """Lee gtk-theme-name y gtk-application-prefer-dark-theme."""
        if not path.exists():
            return None, False
        try:
            config = configparser.ConfigParser()
            config.read(path)
            if "Settings" in config:
                theme = config["Settings"].get("gtk-theme-name")
                dark = config["Settings"].getboolean("gtk-application-prefer-dark-theme", False)
                return theme, dark
        except Exception:
            pass
        return None, False

    def _read_kde_globals(self) -> tuple[Optional[str], bool]:
        """Lee kdeglobals para tema Qt/KDE."""
        if not self.KDE_GLOBALS.exists():
            return None, False
        try:
            config = configparser.ConfigParser()
            config.read(self.KDE_GLOBALS)
            if "General" in config:
                theme = config["General"].get("ColorScheme") or config["General"].get("widgetStyle")
                dark = "dark" in (theme or "").lower() or "breeze-dark" in (theme or "").lower()
                return theme, dark
        except Exception:
            pass
        return None, False

    def _get_gsettings(self) -> tuple[Optional[str], Optional[str]]:
        """Lee gsettings org.gnome.desktop.interface."""
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                capture_output=True, text=True, timeout=2
            )
            theme = result.stdout.strip().strip("'\"")

            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=2
            )
            scheme = result.stdout.strip().strip("'\"")
            return theme, scheme
        except Exception:
            return None, None

    def _resolve_theme(self, gtk_theme, gtk_dark, qt_theme, qt_dark,
                       gsettings_theme, gsettings_scheme, desktop_env) -> str:
        """Resuelve el tema final priorizando: gsettings > GTK > Qt > desktop env."""
        # 1. gsettings (GNOME) - máxima prioridad
        if gsettings_scheme in ("'prefer-dark'", "prefer-dark"):
            return self._map_to_ttkbootstrap(gsettings_theme or "", True)
        if gsettings_scheme in ("'prefer-light'", "prefer-light"):
            return self._map_to_ttkbootstrap(gsettings_theme or "", False)
        if gsettings_theme:
            is_dark = "dark" in gsettings_theme.lower()
            return self._map_to_ttkbootstrap(gsettings_theme, is_dark)

        # 2. GTK settings.ini
        if gtk_theme:
            return self._map_to_ttkbootstrap(gtk_theme, gtk_dark)

        # 3. KDE/Qt
        if qt_theme:
            return self._map_to_ttkbootstrap(qt_theme, qt_dark)

        # 4. Fallback por desktop environment
        if "kde" in desktop_env or "plasma" in desktop_env:
            return self.DEFAULT_DARK if self._kde_is_dark() else self.DEFAULT_LIGHT
        if "gnome" in desktop_env:
            return self.DEFAULT_DARK  # GNOME default dark

        return self.DEFAULT_DARK

    def _map_to_ttkbootstrap(self, gtk_theme: str, is_dark: bool) -> str:
        """Mapea tema GTK/Qt a tema ttkbootstrap."""
        theme_lower = gtk_theme.lower()

        # Buscar en mapeo directo
        for key, value in self.GTK_TO_TTKBOOTSTRAP.items():
            if key.lower() in theme_lower:
                return value

        # Heurística por nombre
        if is_dark or "dark" in theme_lower:
            return self.DEFAULT_DARK
        return self.DEFAULT_LIGHT

    def _is_dark_theme(self, theme: str, gtk_dark: bool, gsettings_scheme: str) -> bool:
        if gsettings_scheme in ("'prefer-dark'", "prefer-dark"):
            return True
        if gsettings_scheme in ("'prefer-light'", "prefer-light"):
            return False
        if gtk_dark:
            return True
        return "dark" in theme.lower()

    def _kde_is_dark(self) -> bool:
        """Detecta si KDE está en modo oscuro."""
        try:
            result = subprocess.run(
                ["kreadconfig5", "--group", "General", "--key", "ColorScheme"],
                capture_output=True, text=True, timeout=2
            )
            scheme = result.stdout.strip().lower()
            return "dark" in scheme or "breeze-dark" in scheme
        except Exception:
            return False

    def get_mapped_theme(self) -> str:
        """Obtiene tema ttkbootstrap mapeado del sistema."""
        info = self.detect_system_theme()
        return self._map_to_ttkbootstrap(info.gtk_theme, info.is_dark)

    # --- Live Reload ---

    def register_callback(self, callback: Callable[[str], None]):
        """Registra callback para cambios de tema: callback(nuevo_tema_ttkbootstrap)."""
        self._callbacks.append(callback)

    def start_monitoring(self, interval: float = 2.0):
        """Inicia monitoreo de cambios en archivos de configuración."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, args=(interval,), daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        """Detiene monitoreo."""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)

    def _monitor_loop(self, interval: float):
        """Monitorea archivos de config y gsettings para cambios."""
        last_gtk3_mtime = self.GTK3_SETTINGS.stat().st_mtime if self.GTK3_SETTINGS.exists() else 0
        last_gtk4_mtime = self.GTK4_SETTINGS.stat().st_mtime if self.GTK4_SETTINGS.exists() else 0
        last_kde_mtime = self.KDE_GLOBALS.stat().st_mtime if self.KDE_GLOBALS.exists() else 0
        last_gsettings = ""

        while not self._stop_event.is_set():
            time.sleep(interval)

            # Verificar archivos
            changed = False
            for path, last_mtime in [
                (self.GTK3_SETTINGS, last_gtk3_mtime),
                (self.GTK4_SETTINGS, last_gtk4_mtime),
                (self.KDE_GLOBALS, last_kde_mtime),
            ]:
                if path.exists():
                    mtime = path.stat().st_mtime
                    if mtime != last_mtime:
                        if path == self.GTK3_SETTINGS:
                            last_gtk3_mtime = mtime
                        elif path == self.GTK4_SETTINGS:
                            last_gtk4_mtime = mtime
                        elif path == self.KDE_GLOBALS:
                            last_kde_mtime = mtime
                        changed = True

            # Verificar gsettings
            try:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                    capture_output=True, text=True, timeout=1
                )
                current = result.stdout.strip()
                if current != last_gsettings:
                    last_gsettings = current
                    changed = True
            except Exception:
                pass

            if changed:
                new_theme = self.get_mapped_theme()
                if new_theme != self._current_theme:
                    self._current_theme = new_theme
                    for cb in self._callbacks:
                        try:
                            cb(new_theme)
                        except Exception as e:
                            print(f"Error en callback de tema: {e}")