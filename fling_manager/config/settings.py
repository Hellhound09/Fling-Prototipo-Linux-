import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from fling_manager.core.game_model import Game, TrainerConfig


class ConfigManager:
    """Gestiona configuración persistente en JSON."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".config" / "fling-trainer-manager"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.config_file = self.config_dir / "config.json"
        self.trainers_file = self.config_dir / "trainers.json"
        self.cache_dir = self.config_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._config = self._load_config()
        self._trainers = self._load_trainers()

    def _load_config(self) -> Dict[str, Any]:
        default_config = {
            "steam_path": os.path.expanduser("~/.steam/steam"),
            "lutris_path": os.path.expanduser("~/.local/share/lutris"),
            "heroic_path": os.path.expanduser("~/.config/heroic"),
            "legendary_path": os.path.expanduser("~/.config/legendary"),
            "bottles_path": os.path.expanduser("~/.local/share/bottles"),
            "portproton_path": os.path.expanduser("~/PortProton"),
            "dotnet_installer_path": "",
            "steamgrid_api_key": "",
            "auto_install_deps": True,
            "install_system_deps": True,
            "default_proton": "auto",
            "theme": "darkly",
            "use_system_theme": True,
            "window_geometry": "1000x700",
        }

        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                    default_config.update(loaded)
            except Exception:
                pass

        return default_config

    def _load_trainers(self) -> Dict[str, Dict]:
        if self.trainers_file.exists():
            try:
                with open(self.trainers_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            print(f"Error guardando config: {e}")

    def save_trainers(self):
        try:
            with open(self.trainers_file, 'w') as f:
                json.dump(self._trainers, f, indent=2)
        except Exception as e:
            print(f"Error guardando trainers: {e}")

    # Config getters/setters
    def get(self, key: str, default=None):
        return self._config.get(key, default)

    def set(self, key: str, value):
        self._config[key] = value
        self.save_config()

    def get_steam_path(self) -> Path:
        return Path(self._config.get("steam_path", os.path.expanduser("~/.steam/steam")))

    def set_steam_path(self, path: str):
        self._config["steam_path"] = path
        self.save_config()

    def get_dotnet_installer(self) -> str:
        return self._config.get("dotnet_installer_path", "")

    def set_dotnet_installer(self, path: str):
        self._config["dotnet_installer_path"] = path
        self.save_config()

    def get_steamgrid_api_key(self) -> str:
        return self._config.get("steamgrid_api_key", "")

    def set_steamgrid_api_key(self, key: str):
        self._config["steamgrid_api_key"] = key
        self.save_config()

    # Trainer management
    def add_trainer(self, game_id: str, trainer_path: str, trainer_name: str = ""):
        from datetime import datetime
        if not trainer_name:
            trainer_name = Path(trainer_path).stem

        self._trainers[game_id] = {
            "game_id": game_id,
            "trainer_path": trainer_path,
            "trainer_name": trainer_name,
            "created_at": datetime.now().isoformat(),
            "enabled": True,
            "extra_args": "",
        }
        self.save_trainers()

    def get_trainer(self, game_id: str) -> Optional[Dict]:
        return self._trainers.get(game_id)

    def remove_trainer(self, game_id: str):
        if game_id in self._trainers:
            del self._trainers[game_id]
            self.save_trainers()

    def get_all_trainers(self) -> Dict[str, Dict]:
        return self._trainers.copy()

    # Cache para iconos SteamGridDB
    def get_icon_cache_path(self, game_id: str) -> Path:
        safe_id = game_id.replace('/', '_').replace(' ', '_')
        return self.cache_dir / f"{safe_id}.png"

    def clear_cache(self):
        for f in self.cache_dir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass