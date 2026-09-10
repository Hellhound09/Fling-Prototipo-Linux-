import os
import re
import sqlite3
import json
import yaml
import configparser
from pathlib import Path
from typing import List, Optional, Dict, Any
from fling_manager.core.game_model import Game, LauncherConfig


def _find_ge_proton_path() -> Optional[Path]:
    """Busca instalación de GE-Proton en herramientas de compatibilidad de Steam."""
    ge_paths = [
        Path.home() / ".local/share/Steam/compatibilitytools.d",
        Path("/usr/share/steam/compatibilitytools.d"),
        Path("/opt/steam/compatibilitytools.d"),
    ]
    
    for base in ge_paths:
        if base.exists():
            for ge_dir in sorted(base.glob("GE-Proton*"), reverse=True):
                candidates = [
                    ge_dir / "files" / "bin" / "wine",
                    ge_dir / "dist" / "bin" / "wine",
                    ge_dir / "bin" / "wine",
                ]
                for c in candidates:
                    if c.exists():
                        return c
    return None


def _find_proton_executable(proton_path: str) -> Optional[Path]:
    """Encuentra el ejecutable proton real dada una ruta base."""
    if not proton_path:
        return None
    path = Path(proton_path)
    if path.name == "proton" and path.exists():
        return path
    # Buscar proton en subdirectorios comunes
    candidates = [
        path / "proton",
        path / "files" / "bin" / "proton",
        path / "dist" / "bin" / "proton",
        path / "bin" / "proton",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


class SteamDetector:
    """Detecta juegos de Steam y sus prefijos Wine."""

    def __init__(self, steam_path: Optional[str] = None):
        self.steam_path = Path(steam_path or os.path.expanduser("~/.steam/steam"))
        self.library_paths = self._get_library_paths()
        self.ge_proton_wine = _find_ge_proton_path()

    def _get_library_paths(self) -> List[Path]:
        """Obtiene todas las bibliotecas de Steam (steamlibrary.vdf)."""
        paths = [self.steam_path]
        vdf_path = self.steam_path / "steamapps" / "libraryfolders.vdf"
        if vdf_path.exists():
            try:
                content = vdf_path.read_text()
                # Parse simple VDF para paths
                for line in content.split('\n'):
                    if 'path' in line.lower():
                        match = re.search(r'"path"\s*"([^"]+)"', line)
                        if match:
                            paths.append(Path(match.group(1)))
            except Exception:
                pass
        return [p for p in paths if p.exists()]

    def detect_games(self) -> List[Game]:
        games = []
        for lib_path in self.library_paths:
            apps_path = lib_path / "steamapps"
            if not apps_path.exists():
                continue

            # Leer appmanifests
            for manifest in apps_path.glob("appmanifest_*.acf"):
                try:
                    content = manifest.read_text(encoding='utf-8', errors='ignore')
                    appid_match = re.search(r'"appid"\s*"(\d+)"', content)
                    name_match = re.search(r'"name"\s*"([^"]+)"', content)
                    installdir_match = re.search(r'"installdir"\s*"([^"]+)"', content)

                    if appid_match and name_match:
                        appid = appid_match.group(1)
                        name = name_match.group(1)
                        installdir = installdir_match.group(1) if installdir_match else ""

                        # Buscar installdir en todas las bibliotecas
                        install_path = None
                        for lib in self.library_paths:
                            candidate = lib / "steamapps" / "common" / installdir
                            if candidate.exists():
                                install_path = str(candidate)
                                break

                        if not install_path:
                            continue

                        # Detectar prefijo Wine (buscar en la misma biblioteca donde está instalado el juego)
                        prefix_path = self._find_prefix(appid, lib_path)
                        proton_path = self._find_proton(appid, prefix_path)

                        # Detectar ejecutable principal
                        exe_name = self._detect_main_exe(install_path) if install_path else ""

                        games.append(Game(
                            id=f"steam_{appid}",
                            name=name,
                            launcher="steam",
                            app_id=appid,
                            install_path=install_path or "",
                            prefix_path=prefix_path or "",
                            proton_path=proton_path or "",
                            runner="proton",
                            exe_name=exe_name,
                        ))
                except Exception:
                    continue
        return games

    def _find_prefix(self, appid: str, library_path: Optional[Path] = None) -> Optional[str]:
        """Busca el prefijo Wine del juego en compatdata.
        Si se proporciona library_path, busca solo allí (donde está instalado el juego).
        """
        if library_path:
            compat = library_path / "steamapps" / "compatdata" / appid / "pfx"
            if compat.exists():
                return str(compat)
        # Fallback: buscar en todas las bibliotecas
        for lib in self.library_paths:
            compat = lib / "steamapps" / "compatdata" / appid / "pfx"
            if compat.exists():
                return str(compat)
        # Fallback: steam default
        default = self.steam_path / "steamapps" / "compatdata" / appid / "pfx"
        return str(default) if default.exists() else None

    def _find_proton(self, appid: str, prefix_path: Optional[str]) -> Optional[str]:
        """Detecta qué Proton usa el juego leyendo config_info."""
        # 1. Intentar leer config_info del prefix del juego
        if prefix_path:
            config_info = Path(prefix_path).parent / "config_info"
            if config_info.exists():
                try:
                    content = config_info.read_text()
                    lines = content.split('\n')
                    if len(lines) >= 2:
                        proton_line = lines[1].strip()
                        if proton_line and ('/Proton' in proton_line or '/proton' in proton_line):
                            import re
                            match = re.search(r'(.*/Proton[^/]*)(?:/files/|/proton)', proton_line)
                            if match:
                                proton_base = match.group(1)
                                proton_exe = _find_proton_executable(proton_base)
                                if proton_exe:
                                    return str(proton_exe)
                            # Fallback
                            proton_base = proton_line.split('/files/')[0].split('/proton')[0]
                            proton_exe = _find_proton_executable(proton_base)
                            if proton_exe:
                                return str(proton_exe)
                except Exception:
                    pass

        # 2. Fallback: Proton Experimental (común)
        experimental = Path.home() / ".local/share/Steam/steamapps/common/Proton - Experimental/proton"
        if experimental.exists():
            return str(experimental)

        # 3. Fallback: GE-Proton si está disponible
        if self.ge_proton_wine:
            ge_proton = self.ge_proton_wine.parent / "proton"
            if ge_proton.exists():
                return str(ge_proton)

        # 4. Buscar cualquier Proton en steamapps/common
        proton_dirs = [
            Path.home() / ".local/share/Steam/steamapps/common",
            Path("/usr/share/steam/steamapps/common"),
        ]
        for base in proton_dirs:
            if base.exists():
                for proton_dir in base.glob("Proton*"):
                    proton_exe = _find_proton_executable(str(proton_dir))
                    if proton_exe:
                        return str(proton_exe)

        return None

    def _detect_main_exe(self, install_path: str) -> str:
        """Intenta detectar el .exe principal del juego."""
        path = Path(install_path)
        exes = list(path.rglob("*.exe"))
        if not exes:
            return ""
        # Heurística: buscar exe con nombre similar a la carpeta
        folder_name = path.name.lower()
        for exe in exes:
            if folder_name in exe.stem.lower():
                return exe.name
        # Fallback: el exe más grande
        return max(exes, key=lambda f: f.stat().st_size).name


class LutrisDetector:
    """Detecta juegos de Lutris."""

    def __init__(self, lutris_path: Optional[str] = None):
        self.lutris_path = Path(lutris_path or os.path.expanduser("~/.local/share/lutris"))
        self.db_path = self.lutris_path / "pga.db"
        self.games_path = self.lutris_path / "games"

    @staticmethod
    def _is_wine_runner(runner: str) -> bool:
        """Verifica si el runner es una variante de Wine."""
        if not runner:
            return False
        runner_lower = runner.lower()
        wine_variants = [
            'wine', 'wine-ge', 'wine-staging', 'wine-ge-proton',
            'wine-vanilla', 'wine-ge-proton', 'wine-staging',
            'proton', 'proton-ge', 'wine-valve', 'wine-valveproton',
            'wine-tkg', 'wine-lutris', 'proton', 'proton-ge',
            'wine-ge-custom', 'wine-tkg', 'wine-tkg-git',
            'wine-lutris', 'wine-lol', 'wine-wow64'
        ]
        return any(variant in runner_lower for variant in wine_variants)

    def _is_wine_game(self, runner: str, config_data: dict) -> bool:
        """Determina si el juego usa Wine (incluyendo variantes)."""
        runner = runner or 'wine'
        if self._is_wine_runner(runner):
            return True
        # Verificar en config_data si hay configuración de wine
        wine_config = config_data.get('wine', {})
        return bool(wine_config.get('version') or wine_config.get('path'))

    def _find_wine_executable(self, wine_version: str = "", wine_path: str = "") -> Optional[str]:
        """Busca el ejecutable de Wine en varias ubicaciones."""
        # 1. Ruta explícita en config
        if wine_path and Path(wine_path).exists():
            return wine_path
        
        # 2. Buscar en runners de Lutris
        if wine_version:
            wine_runner_path = self.lutris_path / "runners" / "wine" / wine_version
            if wine_runner_path.exists():
                for exe_name in ['wine', 'wine64', 'wine.bin']:
                    exe_path = wine_runner_path / exe_name
                    if exe_path.exists():
                        return str(exe_path)
        
        # 3. Buscar en runners de Lutris genéricos
        runners_wine = self.lutris_path / "runners" / "wine"
        if runners_wine.exists():
            for version_dir in runners_wine.iterdir():
                if version_dir.is_dir():
                    for exe_name in ['wine', 'wine64', 'wine.bin']:
                        exe_path = version_dir / exe_name
                        if exe_path.exists():
                            return str(exe_path)
        
        # 4. Buscar wine del sistema
        for exe_name in ['wine', 'wine64']:
            try:
                result = subprocess.run(['which', exe_name], capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
        
        return None

    def _resolve_wine_executable(self, config_data: dict, wine_version: str, wine_path: str) -> Optional[str]:
        """Resuelve el ejecutable de Wine."""
        # 1. Ruta explícita en config
        if wine_path and Path(wine_path).exists():
            return wine_path
        
        # 3. Buscar wine del sistema
        return self._find_wine_executable("", "")

    def _resolve_wine_prefix(self, config_data: dict, row) -> str:
        """Resuelve el prefijo Wine con múltiples fallbacks."""
        # 1. Desde config YAML
        prefix_path = config_data.get('wine', {}).get('prefix', '')
        if prefix_path and Path(prefix_path).exists():
            return prefix_path
        
        # 2. Desde database (row['directory'] puede contener el prefix)
        if row['directory']:
            dir_path = Path(row['directory'])
            # Verificar si el directorio es el prefix (contiene drive_c)
            if (dir_path / "drive_c").exists():
                return str(dir_path)
            # Verificar si hay prefix en subdirectorio
            for sub in ['prefix', 'wineprefix', '.wine']:
                prefix_candidate = dir_path / sub
                if prefix_candidate.exists():
                    return str(prefix_candidate)
        
        # 3. Prefijo por defecto de Lutris
        default_prefix = Path.home() / ".local" / "share" / "lutris" / "prefixes" / row['slug']
        if default_prefix.exists():
            return str(default_prefix)
        
        return ""

    def _find_executable(self, install_path: str, row, config_data: dict) -> str:
        """Encuentra el ejecutable del juego con múltiples estrategias."""
        # 1. Desde database
        if row['executable']:
            exe_path = Path(row['directory']) / row['executable']
            if exe_path.exists():
                return row['executable']
        
        # 2. Desde config YAML
        game_exe = config_data.get('game', {}).get('exe', '')
        if game_exe:
            exe_path = Path(row['directory']) / game_exe
            if exe_path.exists():
                return game_exe
        
        # 3. Buscar .exe en directorio de instalación
        if row['directory']:
            return self._detect_main_exe(row['directory'])
        
        return ""

    def detect_games(self) -> List[Game]:
        """Detecta juegos instalados en Lutris, incluyendo variantes de Wine/Proton."""
        games = []
        if not self.db_path.exists():
            return games

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, name, slug, runner, executable, directory, platform, configpath
                FROM games WHERE installed = 1
            """)

            for row in cursor.fetchall():
                if not row['directory'] or not Path(row['directory']).exists():
                    continue

                # Leer YAML config para más detalles
                config_data = {}
                if row['configpath'] and Path(row['configpath']).exists():
                    try:
                        config_data = yaml.safe_load(Path(row['configpath']).read_text())
                    except Exception:
                        pass

                runner = row['runner'] or config_data.get('runner', 'wine')
                wine_version = config_data.get('wine', {}).get('version', '')
                wine_path = config_data.get('wine', {}).get('path', '')

                # Determinar si es un juego Wine (incluyendo variantes)
                is_wine = self._is_wine_game(runner, config_data)

                # Resolver ejecutable de Wine/Proton
                proton_path = ""
                if self._is_wine_game(runner, config_data):
                    wine_exe = self._resolve_wine_executable(config_data, wine_version, wine_path)
                    if wine_exe:
                        proton_path = wine_exe

                # Resolver prefijo Wine
                prefix_path = self._resolve_wine_prefix(config_data, row)

                # Encontrar ejecutable del juego
                exe_name = self._find_executable(row['directory'], row, config_data)

                games.append(Game(
                    id=f"lutris_{row['slug']}",
                    name=row['name'],
                    launcher="lutris",
                    app_id=row['slug'],
                    install_path=row['directory'],
                    prefix_path=prefix_path,
                    proton_path=proton_path,
                    runner=runner,
                    exe_name=exe_name,
                ))
            conn.close()
        except Exception:
            pass
        return games


class HeroicDetector:
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path or os.path.expanduser("~/.config/heroic"))
        self.games_config_path = self.config_path / "GamesConfig"
        self.default_prefix = Path.home() / "Games" / "Heroic" / "Prefixes" / "shared"

    def detect_games(self) -> List[Game]:
        games = []
        if not self.games_config_path.exists():
            return games

        for config_file in self.games_config_path.glob("*.json"):
            try:
                data = json.loads(config_file.read_text())
                # Los archivos tienen una key que es el ID del juego
                for game_id, config in data.items():
                    if not isinstance(config, dict):
                        continue

                    # Heroic usa winePrefix y wineVersion
                    wine_prefix = config.get('winePrefix', str(self.default_prefix))
                    wine_version = config.get('wineVersion', {})
                    wine_bin = wine_version.get('bin', '')
                    wine_name = wine_version.get('name', 'wine')

                    # Buscar el ejecutable del juego
                    install_path = self._find_game_install_path(game_id, config)
                    if not install_path:
                        continue

                    exe_name = self._detect_main_exe(install_path)

                    games.append(Game(
                        id=f"heroic_{game_id}",
                        name=config.get('name', game_id),
                        launcher="heroic",
                        app_id=game_id,
                        install_path=install_path,
                        prefix_path=wine_prefix,
                        proton_path=wine_bin if wine_bin and Path(wine_bin).exists() else "",
                        runner=wine_name,
                        exe_name=exe_name,
                    ))
            except Exception:
                continue
        return games

    def _find_game_install_path(self, game_id: str, config: dict) -> Optional[str]:
        """Intenta encontrar la ruta de instalación del juego."""
        # Heroic guarda la ruta en config o en el config principal
        install_path = config.get('installPath', '')
        if install_path and Path(install_path).exists():
            return install_path
        # Fallback: buscar en defaultInstallPath
        main_config = self.config_path / "config.json"
        if main_config.exists():
            try:
                main_data = json.loads(main_config.read_text())
                default_path = Path(main_data.get('defaultSettings', {}).get('defaultInstallPath', ''))
                if default_path.exists():
                    # Buscar carpeta del juego
                    for item in default_path.iterdir():
                        if item.is_dir() and game_id.lower() in item.name.lower():
                            return str(item)
            except Exception:
                pass
        return None

    def _detect_main_exe(self, install_path: str) -> str:
        path = Path(install_path)
        exes = list(path.rglob("*.exe"))
        if not exes:
            return ""
        folder_name = path.name.lower()
        for exe in exes:
            if folder_name in exe.stem.lower():
                return exe.name
        return max(exes, key=lambda f: f.stat().st_size).name


class LegendaryDetector:
    """Detecta juegos de Legendary (GOG/Epic)."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path or os.path.expanduser("~/.config/legendary"))
        self.games_db = self.config_path / "legendary.db"

    def detect_games(self) -> List[Game]:
        games = []
        if not self.games_db.exists():
            return games

        try:
            conn = sqlite3.connect(self.games_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM games WHERE installed = 1")
            for row in cursor.fetchall():
                install_path = row['install_path']
                if not install_path or not Path(install_path).exists():
                    continue

                exe_name = self._detect_main_exe(install_path)
                prefix_path = str(Path.home() / ".local" / "share" / "legendary" / "prefixes" / row['app_name'])

                games.append(Game(
                    id=f"legendary_{row['app_name']}",
                    name=row['app_name'],
                    launcher="legendary",
                    app_id=row['app_name'],
                    install_path=install_path,
                    prefix_path=prefix_path,
                    proton_path="",  # Legendary usa wine directo
                    runner="wine",
                    exe_name=exe_name,
                ))
            conn.close()
        except Exception:
            pass
        return games

    def _detect_main_exe(self, install_path: str) -> str:
        path = Path(install_path)
        exes = list(path.rglob("*.exe"))
        if not exes:
            return ""
        folder_name = path.name.lower()
        for exe in exes:
            if folder_name in exe.stem.lower():
                return exe.name
        return max(exes, key=lambda f: f.stat().st_size).name


class BottlesDetector:
    """Detecta juegos de Bottles."""

    def __init__(self, bottles_path: Optional[str] = None):
        self.bottles_path = Path(bottles_path or os.path.expanduser("~/.local/share/bottles"))
        self.bottles_data = self.bottles_path / "bottles"

    def detect_games(self) -> List[Game]:
        games = []
        if not self.bottles_data.exists():
            return games

        for bottle_dir in self.bottles_data.iterdir():
            if not bottle_dir.is_dir():
                continue
            metadata_file = bottle_dir / "metadata.json"
            if not metadata_file.exists():
                continue
            try:
                metadata = json.loads(metadata_file.read_text())
                bottle_name = metadata.get('name', bottle_dir.name)
                programs = metadata.get('programs', [])
                for prog in programs:
                    exe_path = prog.get('path', '')
                    if exe_path and Path(exe_path).exists():
                        games.append(Game(
                            id=f"bottles_{bottle_dir.name}_{prog.get('name', 'game')}",
                            name=prog.get('name', 'Unknown'),
                            launcher="bottles",
                            app_id=f"{bottle_dir.name}_{prog.get('name', 'game')}",
                            install_path=str(Path(exe_path).parent),
                            prefix_path=str(bottle_dir),
                            proton_path="",
                            runner="bottles",
                            exe_name=Path(exe_path).name,
                        ))
            except Exception:
                continue
        return games


class PortProtonDetector:
    """Detecta juegos de PortProton."""

    def __init__(self, portproton_path: Optional[str] = None):
        self.portproton_path = Path(portproton_path or os.path.expanduser("~/PortProton"))

    def detect_games(self) -> List[Game]:
        games = []
        data_path = self.portproton_path / "data"
        if not data_path.exists():
            return games

        for prefix_dir in data_path.iterdir():
            if not prefix_dir.is_dir():
                continue
            # Buscar .exe en el prefix
            drive_c = prefix_dir / "drive_c"
            if not drive_c.exists():
                continue
            for exe in drive_c.rglob("*.exe"):
                try:
                    rel_path = exe.relative_to(drive_c)
                    games.append(Game(
                        id=f"portproton_{prefix_dir.name}_{exe.stem}",
                        name=exe.stem,
                        launcher="portproton",
                        app_id=f"{prefix_dir.name}_{exe.stem}",
                        install_path=str(exe.parent),
                        prefix_path=str(prefix_dir),
                        proton_path=str(self.portproton_path / "data" / "dist" / "proton" / "bin" / "wine"),
                        runner="portproton",
                        exe_name=exe.name,
                    ))
                except Exception:
                    continue
        return games


class GameDetectorManager:
    """Gestiona todos los detectores y unifica resultados."""

    def __init__(self):
        self.detectors = {
            'steam': SteamDetector(),
            'lutris': LutrisDetector(),
            'heroic': HeroicDetector(),
            'legendary': LegendaryDetector(),
            'bottles': BottlesDetector(),
            'portproton': PortProtonDetector(),
        }

    def detect_all(self) -> Dict[str, LauncherConfig]:
        """Detecta juegos en todos los launchers disponibles."""
        results = {}
        for name, detector in self.detectors.items():
            try:
                games = detector.detect_games()
                if games:
                    results[name] = LauncherConfig(
                        name=name,
                        base_path=str(getattr(detector, 'steam_path', getattr(detector, 'lutris_path', getattr(detector, 'config_path', '')))),
                        games=games,
                    )
            except Exception as e:
                print(f"Error detecting {name}: {e}")
        return results

    def get_all_games(self) -> List[Game]:
        """Retorna lista plana de todos los juegos detectados."""
        all_games = []
        for config in self.detect_all().values():
            all_games.extend(config.games)
        return all_games

    def find_game_by_id(self, game_id: str) -> Optional[Game]:
        for game in self.get_all_games():
            if game.id == game_id:
                return game
        return None