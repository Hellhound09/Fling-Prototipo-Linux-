# Fling Trainer Manager

Gestor gráfico para trainers de Fling en Linux. Compatible con **Steam, Lutris, Heroic, Legendary, Bottles y PortProton**.

## Características

- 🎮 **Detección automática** de juegos en Steam, Lutris, Heroic, Legendary, Bottles y PortProton
- 🎯 **Selección visual** de trainer (.exe) con file picker
- 🔧 **Instalación automática** de dependencias: .NET 4.8, VC++ 2019/2022, d3dx9-11, corefonts
- 🔐 **Sudo prompt integrado** para instalación de dependencias de sistema (32-bit)
- 🚀 **Creación de lanzadores** funcionales (.sh + .desktop) para menú de aplicaciones
- 🎨 **Interfaz moderna** con ttkbootstrap (tema darkly por defecto)
- 📋 **Log detallado** con colores y timestamps
- 💾 **Configuración persistente** en JSON (~/.config/fling-trainer-manager/)

## Requisitos

- Python 3.8+
- CachyOS / Arch Linux / derivados (usa pacman)
- Wine/Proton instalado (Steam, Lutris, Heroic, etc.)
- `ttkbootstrap`, `requests`, `PyYAML`, `Jinja2` (se instalan automáticamente)

## Instalación

```bash
# Clonar/descargar el proyecto
cd "/run/media/david/HDD 500GB/Trainers Loader Linux Prototipo/"

# Instalar dependencias Python
pip install -r requirements.txt

# Ejecutar
python main.py
```

## Uso

1. **Seleccionar juego**: El combo lista todos los juegos detectados en Steam, Lutris, Heroic, Legendary, Bottles y PortProton
2. **Seleccionar trainer**: Click en "Examinar" y elige el .exe del trainer de Fling
3. **Instalar dependencias**: Click en "🔧 Instalar .NET 4.8 + VC++ + d3dx" (solo la primera vez)
4. **Crear lanzador**: Click en "🚀 Crear Lanzador" → genera script .sh + entrada .desktop
5. **Lanzar**: Click en "▶ Lanzar Trainer" o busca en tu menú de aplicaciones

## Launchers Soportados

| Launcher | Detección | Prefijo | Proton/Wine |
|----------|-----------|---------|-------------|
| **Steam** | appmanifest + compatdata | `compatdata/<APPID>/pfx` | Proton (Experimental, GE, etc.) |
| **Lutris** | SQLite pga.db + YAML | `~/.local/share/lutris/prefixes/` | Wine runners |
| **Heroic** | JSON GamesConfig | Configurable | Wine/Proton configurable |
| **Legendary** | SQLite legendary.db | `~/.local/share/legendary/prefixes/` | Wine |
| **Bottles** | metadata.json | Bottle directory | Bottles Wine |
| **PortProton** | data/prefixes/ | PortProton data | PortProton Wine |

## Estructura del Proyecto

```
fling-trainer-manager/
├── main.py                          # Entry point
├── requirements.txt
├── pyproject.toml
├── fling_manager/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── game_model.py       # Dataclasses Game, TrainerConfig, LauncherConfig
│   │   ├── detectors.py        # Steam, Lutris, Heroic, Legendary, Bottles, PortProton
│   │   ├── prefix_manager.py   # Wine prefix ops, winetricks, .NET, sudo helper
│   │   └── launcher_builder.py # Templates .sh + .desktop (Jinja2)
│   ├── gui/
│   │   ├── __init__.py
│   │   └── widgets.py          # GameComboBox, TrainerFilePicker, LogView, ProgressDialog
│   └── config/
│       ├── __init__.py
│       └── settings.py         # ConfigManager (JSON persistente)
├── templates/
│   ├── trainer_launcher.sh.j2  # Template script bash
│   └── trainer.desktop.j2      # Template .desktop entry
└── assets/
    └── icon.png
```

## Configuración

Archivo: `~/.config/fling-trainer-manager/config.json`

```json
{
  "steam_path": "~/.steam/steam",
  "lutris_path": "~/.local/share/lutris",
  "heroic_path": "~/.config/heroic",
  "legendary_path": "~/.config/legendary",
  "bottles_path": "~/.local/share/bottles",
  "portproton_path": "~/PortProton",
  "dotnet_installer_path": "/ruta/a/NDP48-x86-x64-AllOS-ENU.exe",
  "steamgrid_api_key": "",
  "auto_install_deps": true,
  "install_system_deps": true,
  "default_proton": "auto",
  "theme": "darkly"
}
```

## Dependencias Instaladas Automáticamente

**Sistema (32-bit via pacman + sudo):**
- lib32-gstreamer, lib32-faudio, lib32-openal, lib32-mpg123
- lib32-vkd3d, lib32-gnutls, lib32-libldap, lib32-freetype2
- lib32-libpng, lib32-libjpeg-turbo, lib32-sqlite, lib32-libusb
- lib32-alsa-lib, lib32-pulseaudio, lib32-vulkan-icd-loader, lib32-opencl-nvidia

**Wine Prefix (winetricks):**
- dotnet48, vcrun2019, vcrun2022, d3dx9, d3dx10, d3dx11, corefonts

## Script Generado (Ejemplo)

```bash
#!/usr/bin/env bash
# Auto-generado por Fling Trainer Manager
set -euo pipefail

export STEAM_COMPAT_APP_ID="1687950"
export STEAM_COMPAT_DATA_PATH="/run/media/david/HDD 1TB/SteamLibrary/steamapps/compatdata/1687950"
export STEAM_COMPAT_CLIENT_INSTALL_PATH="/home/david/.local/share/Steam"
export STEAM_COMPAT_INSTALL_PATH="/run/media/david/HDD 1TB/SteamLibrary/steamapps/common/P5R"
export WINEPREFIX="/run/media/david/HDD 1TB/SteamLibrary/steamapps/compatdata/1687950/pfx"
export MANGOHUD=0
export DWM_DISABLE=1
export WINEDEBUG=-all

pkill -9 wineserver 2>/dev/null || true
sleep 1

exec "/home/david/.local/share/Steam/steamapps/common/Proton - Experimental/proton" run "/ruta/trainer.exe"
```

## Licencia

MIT