from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path
import json


@dataclass
class Game:
    """Representa un juego detectado en cualquier launcher."""
    id: str                     # Único: launcher_appid (ej: steam_1687950)
    name: str                   # Nombre visible
    launcher: str               # steam, lutris, heroic, legendary, bottles, portproton
    app_id: str                 # ID nativo del launcher
    install_path: str           # Ruta donde está el .exe del juego
    prefix_path: str            # Wine prefix del juego
    proton_path: str            # Proton/Wine usado
    runner: str                 # runner de Lutris/Heroic (ej: wine-ge, proton-cachyos)
    exe_name: str               # Ejecutable principal (ej: P5R.exe)
    icon_url: Optional[str] = None      # URL SteamGridDB o local
    icon_path: Optional[str] = None     # Ruta local cacheada
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.launcher.capitalize()})"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Game':
        return cls(**data)


@dataclass
class TrainerConfig:
    """Configuración de un trainer para un juego específico."""
    game_id: str
    trainer_path: str
    trainer_name: str
    created_at: str
    enabled: bool = True
    extra_args: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'TrainerConfig':
        return cls(**data)


@dataclass
class LauncherConfig:
    """Configuración detectada de un launcher."""
    name: str                           # steam, lutris, heroic, legendary, bottles, portproton
    base_path: str                      # Ruta base del launcher
    games: List[Game] = field(default_factory=list)
    proton_candidates: List[str] = field(default_factory=list)
    wine_candidates: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "base_path": self.base_path,
            "games": [g.to_dict() for g in self.games],
            "proton_candidates": self.proton_candidates,
            "wine_candidates": self.wine_candidates,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'LauncherConfig':
        games = [Game.from_dict(g) for g in data.get("games", [])]
        return cls(
            name=data["name"],
            base_path=data["base_path"],
            games=games,
            proton_candidates=data.get("proton_candidates", []),
            wine_candidates=data.get("wine_candidates", []),
        )