"""Proton launcher for Fling Trainer Manager - launches trainers with wine directly, reusing game's wineserver."""

import os
import sys
import time
import threading
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable, Any
from subprocess import DEVNULL, Popen

from .protontricks_util import (
    _get_proton_env,
    _get_fixed_locale_env,
)
from .game_model import Game

logger = logging.getLogger(__name__)


class ProtonLauncher:
    """Launcher that executes trainers using wine directly, reusing the game's wineserver."""

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None):
        self.log_callback = log_callback

    def _log(self, message: str, level: str = "info"):
        if self.log_callback:
            self.log_callback(message, level)
        else:
            logger.log(getattr(logging, level.upper(), logging.INFO), message)

    def _find_game_wineserver(self, prefix_path: Path) -> Optional[int]:
        """Find wineserver PID of the running game using this prefix."""
        # Use process_detector for more robust detection
        try:
            from .process_detector import find_wineserver_for_prefix
            pid = find_wineserver_for_prefix(prefix_path)
            if pid:
                return pid
        except ImportError:
            pass

        # Fallback: try psutil
        try:
            import psutil
            prefix_str = str(prefix_path)
            for proc in psutil.process_iter(['pid', 'environ']):
                try:
                    environ = proc.info.get('environ') or {}
                    if proc.info.get('name') == 'wineserver' and environ.get('WINEPREFIX') == prefix_str:
                        return proc.info['pid']
                except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                    continue
        except ImportError:
            pass

        # Fallback to pgrep
        try:
            for pid_str in subprocess.check_output(["pgrep", "wineserver$"], text=True).split():
                pid = int(pid_str.strip())
                try:
                    environ_data = subprocess.check_output(
                        ["xargs", "-0", "-L1", "-a", f"/proc/{pid}/environ"],
                        text=True, stderr=subprocess.DEVNULL
                    )
                    if f"WINEPREFIX={str(prefix_path)}" in environ_data:
                        return pid
                except (subprocess.CalledProcessError, FileNotFoundError):
                    continue
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def _copy_wineserver_env(self, wineserver_pid: int) -> Dict[str, str]:
        """Copy WINEESYNC and WINEFSYNC from existing wineserver."""
        env_vars = {}
        try:
            environ_data = subprocess.check_output(
                ["xargs", "-0", "-L1", "-a", f"/proc/{wineserver_pid}/environ"],
                text=True, stderr=subprocess.DEVNULL
            )
            for line in environ_data.split('\n'):
                if line.startswith('WINEESYNC=') or line.startswith('WINEFSYNC='):
                    key, value = line.split('=', 1)
                    env_vars[key] = value
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        return env_vars

    def _resolve_wine_bin(self, proton_path: str) -> Path:
        """Resolve wine binary path from Proton installation."""
        proton_exe = Path(proton_path)
        if not proton_exe.exists():
            raise FileNotFoundError(f"Proton executable not found: {proton_path}")

        proton_base = proton_exe.parent
        wine_candidates = [
            proton_base / "files" / "bin" / "wine",
            proton_base / "dist" / "bin" / "wine",
            proton_base / "bin" / "wine",
        ]

        for candidate in wine_candidates:
            if candidate.exists():
                return candidate

        # Fallback: system wine
        system_wine = Path("/usr/bin/wine")
        if system_wine.exists():
            return system_wine

        raise FileNotFoundError(f"Could not find wine binary in {proton_base}")

    def _build_dll_overrides(self, wine_bin: Path, orig_env: Dict[str, str]) -> str:
        """Build WINEDLLOVERRIDES by scanning available DLLs (protontricks style)."""
        proton_dist = wine_bin.parent.parent

        lib64_dlls = {file_.stem for file_ in (proton_dist / "lib64").glob("**/*.dll") if file_.is_file()}
        lib_dlls = {file_.stem for file_ in (proton_dist / "lib").glob("**/*.dll") if file_.is_file()}
        available_dlls = lib64_dlls | lib_dlls

        from .protontricks_util import _DLL_OVERRIDES

        dll_overrides = {}
        for dll_override in orig_env.get("WINEDLLOVERRIDES", "").split(";"):
            if "=" not in dll_override:
                continue
            settings, value = dll_override.split("=")
            for setting in settings.split(","):
                dll_overrides[setting] = value

        for name, setting in _DLL_OVERRIDES.items():
            if name in available_dlls and name not in dll_overrides:
                dll_overrides[name] = setting

        return ";".join(f"{name}={setting}" for name, setting in dll_overrides.items())

    def _build_trainer_environment(self, game: Game, wine_bin: Path, wineserver_env: Dict[str, str]) -> Dict[str, str]:
        """Build complete Steam/Proton environment for trainer."""
        env = os.environ.copy()

        prefix_path = Path(game.prefix_path)
        compatdata_path = prefix_path.parent
        install_path = Path(game.install_path) if game.install_path else compatdata_path / "pfx"
        proton_dist = wine_bin.parent.parent

        # Core Wine environment
        env["WINEPREFIX"] = str(prefix_path)
        env["WINEDLLPATH"] = ":".join([
            str(proton_dist / "lib64" / "wine"),
            str(proton_dist / "lib" / "wine"),
        ])
        env["PATH"] = ":".join([
            str(wine_bin.parent),
            env["PATH"],
        ])

        # Steam Compat variables (CRITICAL for FLing trainers to find game process)
        env["WINEPREFIX"] = str(prefix_path)
        env["STEAM_COMPAT_APP_ID"] = game.app_id
        env["STEAM_COMPAT_DATA_PATH"] = str(compatdata_path)
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH", "/home/david/.steam/steam")
        env["STEAM_COMPAT_INSTALL_PATH"] = str(install_path)
        env["STEAM_COMPAT_MEDIA_PATH"] = str(compatdata_path / "reports")
        env["STEAM_COMPAT_MOUNTS"] = f"{prefix_path}:{install_path}"
        env["SteamAppId"] = game.app_id
        env["SteamGameId"] = game.app_id

        # WINEDLLOVERRIDES (DXVK, vkd3d, nvapi, BattlEye)
        env["WINEDLLOVERRIDES"] = self._build_dll_overrides(wine_bin, {})

        # Steam Runtime / Proton environment
        env.update(_get_fixed_locale_env())

        wine_environ = env.copy()
        wine_environ.update(_get_proton_env(
            type('ProtonApp', (), {
                'install_path': Path(wine_bin).parent.parent.parent,
                'proton_dist_path': proton_dist,
                'name': 'proton',
                'required_tool_app': None,
                'required_tool_appid': None,
            })(),
            type('SteamApp', (), {
                'appid': int(game.app_id),
                'prefix_path': prefix_path,
                'install_path': install_path,
            })(),
            wine_environ,
        ))
        env.update(wine_environ)

        # Copy wineserver sync settings (WINEESYNC, WINEFSYNC)
        env.update(wineserver_env)

        # Performance settings
        if "WINEFSYNC" not in env and not env.get("PROTON_NO_FSYNC"):
            env["WINEFSYNC"] = "1"
        if "WINEESYNC" not in env and not env.get("PROTON_NO_ESYNC"):
            env["WINEESYNC"] = "1"

        # Performance & compatibility
        env["WINE_LARGE_ADDRESS_AWARE"] = "1"
        env["DXVK_ENABLE_NVAPI"] = "1"
        env["WINE_LARGE_ADDRESS_AWARE"] = "1"

        # Disable debug output
        env["WINEDEBUG"] = "-all"
        env["MANGOHUD"] = "0"
        env["DWM_DISABLE"] = "1"

        return env

    def _find_game_process(self, game: Game) -> Optional[Dict]:
        """Find game process info (Linux PID, Wine PID, wineserver PID)."""
        prefix_str = str(game.prefix_path)
        app_id = game.app_id

        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'cmdline', 'environ']):
                try:
                    environ = proc.info.get('environ') or {}
                    cmdline = ' '.join(proc.info.get('cmdline') or [])

                    # Check if this process belongs to our game prefix
                    if environ.get('WINEPREFIX') == str(game.prefix_path):
                        # Found game process, get wineserver
                        wineserver_pid = None
                        for child in psutil.Process(proc.info['pid']).children(recursive=True):
                            if child.name() == 'wineserver':
                                wineserver_pid = child.pid
                                break

                        return {
                            'linux_pid': proc.info['pid'],
                            'wine_pid': proc.info['pid'],
                            'wineserver_pid': wineserver_pid,
                            'cmdline': cmdline[:200],
                        }

                    # Also check by Steam AppId in cmdline
                    if f"SteamAppId={app_id}" in cmdline or f"SteamGameId={app_id}" in cmdline:
                        wineserver_pid = None
                        for child in psutil.Process(proc.info['pid']).children(recursive=True):
                            if child.name() == 'wineserver':
                                wineserver_pid = child.pid
                                break

                        return {
                            'linux_pid': proc.info['pid'],
                            'wine_pid': proc.info['pid'],
                            'wineserver_pid': wineserver_pid,
                            'cmdline': cmdline[:200],
                        }
                except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                    continue
        except ImportError:
            pass

        return None

    def launch_trainer(
        self,
        game: Game,
        trainer_windows_path: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, str]:
        """Launch trainer using wine directly, reusing game's wineserver."""
        try:
            self._log(f"🚀 Lanzando trainer para {game.name}...", "success")

            # Resolve wine binary from Proton
            wine_bin = self._resolve_wine_bin(game.proton_path)
            prefix_path = Path(game.prefix_path)

            if not prefix_path.exists():
                return False, f"Prefix no existe: {prefix_path}"

            # 1. Find game's wineserver (reutilizar el del juego)
            self._log("🔍 Detectando wineserver del juego...", "info")
            game_wineserver_pid = self._find_game_wineserver(prefix_path)

            wineserver_env = {}
            if game_wineserver_pid:
                self._log(f"✅ Wineserver del juego encontrado PID={game_wineserver_pid}", "success")
                wineserver_env = self._copy_wineserver_env(game_wineserver_pid)
                if wineserver_env:
                    self._log(f"📋 Copiando vars: {', '.join(wineserver_env.keys())}", "debug")
            else:
                self._log("⚠ No se encontró wineserver del juego, se usará uno nuevo", "warning")

            # Detectar proceso del juego para logging
            game_proc_info = self._find_game_process(game)
            if game_proc_info:
                self._log(f"🎮 Juego detectado: Linux PID={game_proc_info['linux_pid']}, wineserver={game_proc_info.get('wineserver_pid')}", "info")

            # 2. Build complete trainer environment
            env = self._build_trainer_environment(game, wine_bin, wineserver_env)

            # 3. Launch with wine directly (NOT proton run)
            trainer_exe = trainer_windows_path.replace("/", "\\")

            self._log(f"Ejecutando trainer: {trainer_exe}", "info")
            self._log(f"Usando wine: {wine_bin}", "debug")

            cmd = [str(wine_bin), trainer_exe]

            proc = Popen(
                cmd,
                env=env,
                stdin=DEVNULL,
                stdout=DEVNULL,
                stderr=DEVNULL,
                start_new_session=False,  # CRITICAL: share session with game
            )

            self._log(f"✅ Trainer lanzado (PID: {proc.pid})", "success")

            def monitor():
                time.sleep(2)
                if proc.poll() is None:
                    self._log("✅ Trainer ejecutándose correctamente", "success")
                else:
                    self._log(f"⚠ Trainer terminó con código {proc.returncode}", "warning")

            threading.Thread(target=monitor, daemon=True).start()

            return True, str(proc.pid)

        except Exception as e:
            self._log(f"❌ Error lanzando trainer: {e}", "error")
            import traceback
            traceback.print_exc()
            return False, str(e)

    def cleanup(self):
        # No keepalive to clean up anymore
        pass


def main():
    """Entry point for CLI: python -m fling_manager.core.proton_launcher <game_id> <trainer_windows_path>"""
    if len(sys.argv) < 3:
        print("Uso: python -m fling_manager.core.proton_launcher <game_id> <trainer_windows_path>")
        sys.exit(1)

    game_id = sys.argv[1]
    trainer_windows_path = sys.argv[2]

    # Initialize detector manager
    from fling_manager.core.detectors import GameDetectorManager
    detector_manager = GameDetectorManager()
    games = detector_manager.get_all_games()
    game = next((g for g in games if g.id == game_id), None)

    if not game:
        print(f"Juego no encontrado: {game_id}")
        sys.exit(1)

    launcher = ProtonLauncher()
    success, msg = launcher.launch_trainer(game, trainer_windows_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()