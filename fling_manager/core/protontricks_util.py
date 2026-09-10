"""Vendorized protontricks utilities for Proton/Wine environment management.
Based on protontricks (https://github.com/Matoking/protontricks) - MIT License.
"""

import os
import sys
import shutil
import logging
import tempfile
import subprocess
import importlib.resources
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired, check_output, run
from typing import Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

SUPPORTED_STEAM_RUNTIMES = [
    "Steam Linux Runtime - Soldier",
    "Steam Linux Runtime - Sniper",
    "Steam Linux Runtime 2.0 (soldier)",
    "Steam Linux Runtime 3.0 (sniper)",
]

OS_RELEASE_PATHS = [
    "/run/host/os-release",
    "/etc/os-release",
]

_DLL_OVERRIDES = {
    "beclient": "b,n",
    "beclient_x64": "b,n",
    "dxgi": "n",
    "d3d9": "n",
    "d3d10core": "n",
    "d3d11": "n",
    "d3d12": "n",
    "d3d12core": "n",
    "nvapi": "n",
    "nvapi64": "n",
    "nvofapi64": "n",
    "nvcuda": "b",
}

_WINE_DEFAULT_ENV_VARS = {
    "WINE_LARGE_ADDRESS_AWARE": "1",
    "DXVK_ENABLE_NVAPI": "1",
}

RUNTIME_ROOT_GLOB_PATTERNS = (
    "var/*/files/",
    "*/files/",
)

WINE_SCRIPT_TEMPLATE = """#!/bin/bash
# Helper script created by Fling Trainer Manager to run Wine binaries using Steam Runtime
set -o errexit

function log_debug () {
    if [[ "$PROTONTRICKS_LOG_LEVEL" != "DEBUG" ]]; then
        return
    fi
}

function log_info () {
    if [[ "$PROTONTRICKS_LOG_LEVEL" = "WARNING" ]]; then
        return
    fi
    log "$@"
}

function log_warning () {
    if [[ "$PROTONTRICKS_LOG_LEVEL" = "INFO" || "$PROTONTRICKS_LOG_LEVEL" = "WARNING" ]]; then
        return
    fi
    log "$@"
}

function log () {
    >&2 echo "fling-trainer-manager - $(basename "$0") $$: $*"
}

PROTONTRICKS_PROXY_SCRIPT_PATH="@@script_path@@"

BLACKLISTED_ROOT_DIRS=(
    /bin /dev /lib /lib64 /proc /run /sys /var /usr
)

ADDITIONAL_MOUNT_DIRS=(
    /run/media "$PROTON_PATH" "$WINEPREFIX"
)

WINESERVER_ENV_VARS_TO_COPY=(
    WINEESYNC WINEFSYNC
)

if [[ -n "$PROTONTRICKS_BACKGROUND_WINESERVER"
       && "$0" = "@@script_path@@"
    ]]; then
    if [[ "$(basename "$0")" = "wineserver"
        && "$1" = "-w"
        ]]; then
        log_info "Touching '$PROTONTRICKS_TEMP_PATH/restart' to restart wineserver."
        touch "$PROTONTRICKS_TEMP_PATH/restart"
    fi
fi

if [[ -z "$PROTONTRICKS_FIRST_START" ]]; then
    if [[ "$PROTONTRICKS_STEAM_RUNTIME" = "bwrap" ]]; then
        launch_script=""
        script_names=('pressure-vessel-launch' 'steam-runtime-launch-client')
        for name in "${script_names[@]}"; do
            if [[ -f "$STEAM_RUNTIME_PATH/pressure-vessel/bin/$name" ]]; then
                launch_script="$STEAM_RUNTIME_PATH/pressure-vessel/bin/$name"
                log_info "Found Steam Runtime launch client at $launch_script"
            fi
        done

        if [[ "$launch_script" = "" ]]; then
            echo "Launch script could not be found, aborting..."
            exit 1
        fi

        export STEAM_RUNTIME_LAUNCH_SCRIPT="$launch_script"
    fi

    wineserver_found=false
    log_info "Checking for running wineserver instance"

    while read -r pid; do
        if [[ $(xargs -0 -L1 -a "/proc/${pid}/environ" | grep "^WINEPREFIX=${WINEPREFIX}") ]] &> /dev/null; then
            if [[ "$pid" = "$$" ]]; then
                continue
            fi
            wineserver_found=true
            wineserver_pid="$pid"
            log_info "Found running wineserver instance with PID ${wineserver_pid}"
        fi
    done < <(pgrep "wineserver$")

    if [[ "$wineserver_found" = true ]]; then
        wineserver_env_vars=$(xargs -0 -L1 -a "/proc/${wineserver_pid}/environ" 2> /dev/null || echo "")
        for env_name in "${WINESERVER_ENV_VARS_TO_COPY[@]}"; do
            env_declr=$(echo "$wineserver_env_vars" | grep "^${env_name}=" || :)
            if [[ -n "$env_declr" ]]; then
                log_info "Copying env var from running wineserver: ${env_declr}"
                export "${env_declr?}"
            fi
        done
    fi

    if [[ "$wineserver_found" = false ]]; then
        if [[ -z "$WINEFSYNC" ]]; then
            if [[ -z "$PROTON_NO_FSYNC" || "$PROTON_NO_FSYNC" = "0" ]]; then
                log_info "Setting default env: WINEFSYNC=1"
                export WINEFSYNC=1
            fi
        fi

        if [[ -z "$WINEESYNC" ]]; then
            if [[ -z "$PROTON_NO_ESYNC" || "$PROTON_NO_ESYNC" = "0" ]]; then
                log_info "Setting default env: WINEESYNC=1"
                export WINEESYNC=1
            fi
        fi
    fi

    export PROTONTRICKS_FIRST_START=1
fi

if [[ -n "$PROTONTRICKS_INSIDE_STEAM_RUNTIME"
       || "$PROTONTRICKS_STEAM_RUNTIME" = "legacy"
       || "$PROTONTRICKS_STEAM_RUNTIME" = "off"
    ]]; then

    if [[ -n "$PROTONTRICKS_INSIDE_STEAM_RUNTIME" ]]; then
        log_info "Starting Wine process inside the container"
    else
        log_info "Starting Wine process directly, Steam runtime: $PROTONTRICKS_STEAM_RUNTIME"
    fi

    if [[ "$PROTONTRICKS_STEAM_RUNTIME" = "bwrap" ]]; then
        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH":"$PROTON_LD_LIBRARY_PATH"
        log_info "Appending to LD_LIBRARY_PATH: $PROTON_LD_LIBRARY_PATH"
    elif [[ "$PROTONTRICKS_STEAM_RUNTIME" = "legacy" ]]; then
        export LD_LIBRARY_PATH="$PROTON_LD_LIBRARY_PATH"
        log_info "LD_LIBRARY_PATH set to $LD_LIBRARY_PATH"
    fi
    exec "$PROTON_DIST_PATH"/bin/@@name@@ "$@" || :
elif [[ "$PROTONTRICKS_STEAM_RUNTIME" = "bwrap" ]]; then
    log_info "Starting Wine process using 'pressure-vessel-launch'"

    bus_name="com.github.Matoking.protontricks.App${STEAM_APPID}_${PROTONTRICKS_SESSION_ID}"

    env_params=()
    for env_name in $(compgen -e); do
        if [[ "$env_name" = "XAUTHORITY"
              || "$env_name" = "DISPLAY"
              || "$env_name" = "WAYLAND_DISPLAY" ]]; then
            continue
        fi
        env_params+=(--pass-env "${env_name}")
    done

    exec "$STEAM_RUNTIME_LAUNCH_SCRIPT" \
    --share-pids --bus-name="$bus_name" \
    --directory "$PWD" \
    --env=PROTONTRICKS_INSIDE_STEAM_RUNTIME=1 \
    "${env_params[@]}" -- "$PROTONTRICKS_PROXY_SCRIPT_PATH" "$@"
else
    echo "Unknown PROTONTRICKS_STEAM_RUNTIME value $PROTONTRICKS_STEAM_RUNTIME"
    exit 1
fi
"""

WINESERVER_KEEPALIVE_SH_SCRIPT = """#!/bin/bash
# wineserver keepalive script for Fling Trainer Manager
set -o errexit

function log () {
    >&2 echo "fling-trainer-manager - wineserver-keepalive $$: $*"
}

KEEPALIVE_BAT_PATH="@@keepalive_bat_path@@"
TEMP_PATH="$PROTONTRICKS_TEMP_PATH"

log "Starting wineserver keepalive"

while true; do
    if [[ -f "$TEMP_PATH/restart" ]]; then
        log "Restart requested, restarting wineserver"
        rm -f "$TEMP_PATH/restart"
        wineserver -w
        continue
    fi

    if ! pgrep -x wineserver > /dev/null; then
        log "wineserver not running, exiting keepalive"
        break
    fi

    sleep 1
done

log "wineserver keepalive exiting"
"""

WINESERVER_KEEPALIVE_BATCH_SCRIPT = """@echo off
REM wineserver keepalive batch script for Fling Trainer Manager
:loop
if exist "%PROTONTRICKS_TEMP_PATH%\restart" (
    del "%PROTONTRICKS_TEMP_PATH%\restart"
    wineserver -w
)
timeout /t 1 >nul
goto loop
"""

BWRAP_LAUNCHER_SH_SCRIPT = """#!/bin/bash
# bwrap launcher for Fling Trainer Manager
set -o errexit

exec pressure-vessel-launch "$@"
"""


def is_steam_deck() -> bool:
    for path in OS_RELEASE_PATHS:
        try:
            lines = Path(path).read_text("utf-8").split("\n")
        except FileNotFoundError:
            continue
        if "ID=steamos" in lines and "VARIANT_ID=steamdeck" in lines:
            return True
    return False


def is_steamos() -> bool:
    for path in OS_RELEASE_PATHS:
        try:
            lines = Path(path).read_text("utf-8").split("\n")
        except FileNotFoundError:
            continue
        if "ID=steamos" in lines and "ID_LIKE=arch" in lines:
            return True
    return False


def get_host_library_paths() -> str:
    result = run(
        ["/sbin/ldconfig", "-XNv"],
        check=True, stdout=PIPE, stderr=PIPE
    )
    lines = result.stdout.decode("utf-8").split("\n")
    paths = [
        line.split(":")[0] for line in lines
        if line.startswith("/") and ":" in line
    ]
    return ":".join(paths)


def find_runtime_app_root(runtime_app: "ProtonApp") -> Path:
    for pattern in RUNTIME_ROOT_GLOB_PATTERNS:
        try:
            return next(runtime_app.install_path.glob(pattern))
        except StopIteration:
            pass
    raise RuntimeError(f"Could not find Steam Runtime runtime root for {runtime_app.name}")


def get_runtime_library_paths(proton_app: "ProtonApp", use_bwrap: bool = True) -> str:
    if use_bwrap:
        return ":".join([
            str(proton_app.proton_dist_path / "lib"),
            str(proton_app.proton_dist_path / "lib64"),
        ])

    runtime_root = find_runtime_app_root(proton_app.required_tool_app)
    return ":".join([
        str(proton_app.proton_dist_path / "lib"),
        str(proton_app.proton_dist_path / "lib64"),
        get_host_library_paths(),
        str(runtime_root / "lib" / "i386-linux-gnu"),
        str(runtime_root / "lib" / "x86_64-linux-gnu"),
    ])


def get_legacy_runtime_library_paths(legacy_steam_runtime_path: Path, proton_app: "ProtonApp") -> str:
    steam_runtime_paths = check_output([
        str(legacy_steam_runtime_path / "run.sh"),
        "--print-steam-runtime-library-paths"
    ])
    steam_runtime_paths = str(steam_runtime_paths, "utf-8")
    return ":".join([
        str(proton_app.proton_dist_path / "lib"),
        str(proton_app.proton_dist_path / "lib64"),
        steam_runtime_paths,
    ])


def _get_fixed_locale_env() -> Dict[str, str]:
    if not is_steamos():
        return {}

    supported_locales = run(
        ["locale", "-a"], check=True, stdout=PIPE, stderr=DEVNULL
    ).stdout.decode("utf-8").splitlines()
    supported_locales = [
        locale.normalize(locale_) for locale_ in supported_locales
    ]

    locale_output = run(
        ["locale"], check=True, stdout=PIPE, stderr=DEVNULL
    ).stdout.decode("utf-8").splitlines()
    locale_output = [value.split("=") for value in locale_output]
    locale_settings = {
        value[0]: value[1].strip('"') for value in locale_output
    }

    fixed_env = {}
    for category, locale_ in locale_settings.items():
        if locale_.strip() == "":
            continue
        locale_ = locale.normalize(locale_)
        if locale_ not in supported_locales:
            fixed_env[category] = "en_US.UTF-8"

    if fixed_env:
        logger.warning(
            "Found locale categories configured with missing locales. "
            "Reset to 'en_US.UTF-8' for: %s",
            ", ".join(fixed_env.keys())
        )

    return fixed_env


class ProtonApp:
    """Minimal Proton app representation for environment building."""
    def __init__(self, install_path: Path, proton_dist_path: Path, name: str,
                 required_tool_app: Optional["ProtonApp"] = None,
                 required_tool_appid: Optional[int] = None):
        self.install_path = install_path
        self.proton_dist_path = proton_dist_path
        self.name = name
        self.required_tool_app = required_tool_app
        self.required_tool_appid = required_tool_appid


class SteamApp:
    """Minimal Steam app representation."""
    def __init__(self, appid: int, prefix_path: Path, install_path: Path):
        self.appid = appid
        self.prefix_path = prefix_path
        self.install_path = install_path


def _get_proton_env(proton_app: ProtonApp, steam_app: SteamApp, orig_env: Dict[str, str]) -> Dict[str, str]:
    """Build Proton environment variables (DXVK, vkd3d, nvapi, etc.)."""
    new_env = {}
    dist_path = proton_app.proton_dist_path

    lib64_dlls = {file_.stem for file_ in (dist_path / "lib64").glob("**/*.dll")}
    lib_dlls = {file_.stem for file_ in (dist_path / "lib").glob("**/*.dll")}
    available_dlls = lib64_dlls | lib_dlls

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

    new_env["WINEDLLOVERRIDES"] = ";".join(
        f"{name}={setting}" for name, setting in dll_overrides.items()
    )

    is_gstreamer_available = (dist_path / "lib/gstreamer-1.0").is_dir()
    if is_gstreamer_available:
        new_env["GST_PLUGIN_SYSTEM_PATH_1_0"] = ":".join([
            str(dist_path / "lib64/gstreamer-1.0"),
            str(dist_path / "lib/gstreamer-1.0"),
        ])
        new_env["WINE_GST_REGISTRY_DIR"] = str(
            steam_app.prefix_path.parent / "gstreamer-1.0"
        )

    for name, value in _WINE_DEFAULT_ENV_VARS.items():
        if name not in orig_env:
            new_env[name] = value

    return new_env


def create_wine_bin_dir(proton_app: ProtonApp, cache_base: Path, use_bwrap: bool = True) -> Path:
    """Create proxy scripts for wine/wineserver in cache directory."""
    binaries = list((proton_app.proton_dist_path / "bin").iterdir())
    bin_path = cache_base / "proton" / proton_app.name / "bin"
    bin_path.mkdir(parents=True, exist_ok=True)

    shutil.rmtree(str(bin_path), ignore_errors=True)
    bin_path.mkdir(parents=True)

    for binary in binaries:
        proxy_script_path = bin_path / binary.name
        content = WINE_SCRIPT_TEMPLATE.replace("@@name@@", binary.name)
        content = content.replace("@@script_path@@", str(proxy_script_path))
        proxy_script_path.write_text(content, encoding="utf-8")
        proxy_script_path.chmod(proxy_script_path.stat().st_mode | 0o111)

    (bin_path / "wineserver-keepalive.bat").write_text(WINESERVER_KEEPALIVE_BATCH_SCRIPT)
    keepalive_shell_script = bin_path / "wineserver-keepalive"
    keepalive_shell_script.write_text(
        WINESERVER_KEEPALIVE_SH_SCRIPT.replace("@@keepalive_bat_path@@", str(bin_path / "wineserver-keepalive.bat"))
    )
    keepalive_shell_script.chmod(keepalive_shell_script.stat().st_mode | 0o111)
    launcher_script = bin_path / "bwrap-launcher"
    launcher_script.write_text(BWRAP_LAUNCHER_SH_SCRIPT)
    launcher_script.chmod(launcher_script.stat().st_mode | 0o111)

    return bin_path


def run_command(
    proton_app: ProtonApp,
    steam_app: SteamApp,
    command: List[str],
    use_steam_runtime: bool = False,
    legacy_steam_runtime_path: Optional[Path] = None,
    use_bwrap: Optional[bool] = None,
    start_wineserver: Optional[bool] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> int:
    """Run a command with full Proton environment."""
    if env is None:
        env = {}

    wine_environ = os.environ.copy()
    wine_environ.update(env)

    user_provided_wine = os.environ.get("WINE", False)
    user_provided_wineserver = os.environ.get("WINESERVER", False)

    wine_environ["WINEPREFIX"] = str(steam_app.prefix_path)

    if os.environ.get("STEAM_COMPAT_DATA_PATH"):
        prefix_path = Path(os.environ["STEAM_COMPAT_DATA_PATH"]) / "pfx"
        wine_environ["WINEPREFIX"] = str(prefix_path)

    wine_environ["WINEDLLPATH"] = ":".join([
        str(proton_app.proton_dist_path / "lib64" / "wine"),
        str(proton_app.proton_dist_path / "lib" / "wine"),
    ])

    wine_environ["PATH"] = ":".join([
        str(proton_app.proton_dist_path / "bin"),
        wine_environ["PATH"],
    ])

    wine_environ["PROTON_PATH"] = str(proton_app.install_path)
    wine_environ["PROTON_DIST_PATH"] = str(proton_app.proton_dist_path)
    wine_environ["STEAM_APP_PATH"] = str(steam_app.install_path)
    wine_environ["STEAM_APPID"] = str(steam_app.appid)
    wine_environ.pop("WINEARCH", "")
    wine_environ.update(_get_fixed_locale_env())
    wine_environ.update(_get_proton_env(proton_app, steam_app, wine_environ))

    wine_environ["PROTONTRICKS_STEAM_RUNTIME"] = "off"
    if use_steam_runtime:
        if use_bwrap is None:
            use_bwrap = bool(proton_app.required_tool_app)
        if start_wineserver is None:
            start_wineserver = use_bwrap

        if proton_app.required_tool_app:
            wine_environ["STEAM_RUNTIME_PATH"] = str(proton_app.required_tool_app.install_path)
            wine_environ["PROTON_LD_LIBRARY_PATH"] = get_runtime_library_paths(proton_app, use_bwrap=use_bwrap)
            wine_environ["PROTONTRICKS_STEAM_RUNTIME"] = "bwrap" if use_bwrap else "legacy"
        else:
            wine_environ["PROTONTRICKS_STEAM_RUNTIME"] = "legacy"
            wine_environ["PROTON_LD_LIBRARY_PATH"] = get_legacy_runtime_library_paths(legacy_steam_runtime_path, proton_app)
            use_bwrap = False

    cache_base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "fling-trainer-manager"
    wine_bin_dir = create_wine_bin_dir(proton_app, cache_base, use_bwrap)
    wine_environ["LEGACY_STEAM_RUNTIME_PATH"] = str(legacy_steam_runtime_path)
    wine_environ["PATH"] = ":".join([str(wine_bin_dir), wine_environ["PATH"]])

    if not user_provided_wine:
        wine_environ["WINE"] = str(wine_bin_dir / "wine")
        wine_environ["WINE_BIN"] = str(proton_app.proton_dist_path / "bin" / "wine")
    wine_environ["WINELOADER"] = wine_environ["WINE"]

    if not user_provided_wineserver:
        wine_environ["WINESERVER"] = str(wine_bin_dir / "wineserver")
        wine_environ["WINESERVER_BIN"] = str(proton_app.proton_dist_path / "bin" / "wineserver")

    temp_dir = Path(tempfile.mkdtemp(prefix="fling-trainer-"))
    wine_environ["PROTONTRICKS_TEMP_PATH"] = str(temp_dir)
    wine_environ["PROTONTRICKS_SESSION_ID"] = temp_dir.name.split("-")[-1]

    if start_wineserver:
        wine_environ["PROTONTRICKS_BACKGROUND_WINESERVER"] = "1"

    launcher_process = None
    keepalive_process = None
    try:
        if use_bwrap:
            launcher_read_fd, launcher_write_fd = os.pipe2(os.O_CLOEXEC)
            launcher_process = _start_process(
                [str(wine_bin_dir / "bwrap-launcher"), str(launcher_write_fd)],
                wait=False,
                pass_fds=[launcher_write_fd],
                env=wine_environ
            )
            os.close(launcher_write_fd)
            with open(launcher_read_fd, "rb") as reader:
                reader.read()
            try:
                launcher_process.wait(timeout=0.1)
                raise RuntimeError(f"bwrap launcher crashed, returncode: {launcher_process.returncode}")
            except TimeoutExpired:
                pass

        if start_wineserver:
            keepalive_process = _start_process(
                str(wine_bin_dir / "wineserver-keepalive"),
                wait=False,
                env=wine_environ,
                stdout=DEVNULL,
            )

        process = _start_process(
            command, wait=True, env=wine_environ, cwd=str(cwd) if cwd else None
        )
        return process.returncode
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        if keepalive_process:
            keepalive_process.terminate()
        if launcher_process:
            launcher_process.terminate()
            launcher_process.wait()


def _start_process(args, wait=False, **kwargs):
    process = Popen(args=args, **kwargs)
    if wait:
        process.wait()
    return process


def detect_existing_wineserver(prefix_path: Path) -> Tuple[Optional[int], Dict[str, str]]:
    """Detect existing wineserver for the given prefix.
    Returns (pid, env_vars_dict) or (None, {}) if not found.
    """
    try:
        for pid_str in subprocess.check_output(["pgrep", "wineserver$"], text=True).split():
            pid = int(pid_str.strip())
            try:
                environ_data = subprocess.check_output(
                    ["xargs", "-0", "-L1", "-a", f"/proc/{pid}/environ"],
                    text=True, stderr=DEVNULL
                )
                if f"WINEPREFIX={prefix_path}" in environ_data:
                    env_vars = {}
                    for line in environ_data.splitlines():
                        if "=" in line:
                            key, value = line.split("=", 1)
                            if key in ("WINEESYNC", "WINEFSYNC"):
                                env_vars[key] = value
                    return pid, env_vars
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
    except subprocess.CalledProcessError:
        pass
    return None, {}


def start_wineserver_keepalive(prefix_path: Path, proton_bin_dir: Path, temp_dir: Path) -> subprocess.Popen:
    """Start wineserver keepalive background process."""
    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix_path)
    env["PROTONTRICKS_TEMP_PATH"] = str(temp_dir)
    env["PROTONTRICKS_BACKGROUND_WINESERVER"] = "1"
    return subprocess.Popen(
        [str(proton_bin_dir / "wineserver-keepalive")],
        env=env,
        stdout=DEVNULL,
        stderr=DEVNULL,
    )