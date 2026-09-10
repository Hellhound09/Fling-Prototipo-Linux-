"""Process detector for finding game processes in Linux and Wine."""

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def find_game_process_by_prefix(prefix_path: Path) -> Optional[Dict[str, Any]]:
    """Find game process by Wine prefix path."""
    prefix_str = str(prefix_path)
    
    if not PSUTIL_AVAILABLE:
        return None
    
    try:
        for proc in psutil.process_iter(['pid', 'cmdline', 'environ']):
            try:
                environ = proc.info.get('environ') or {}
                if environ.get('WINEPREFIX') == prefix_str:
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
                        'cmdline': ' '.join(proc.info.get('cmdline') or [])[:200],
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
    except ImportError:
        pass
    
    return None


def find_game_process_by_appid(app_id: str) -> Optional[Dict[str, Any]]:
    """Find game process by Steam AppId."""
    if not PSUTIL_AVAILABLE:
        return None
    
    try:
        for proc in psutil.process_iter(['pid', 'cmdline', 'environ']):
            try:
                environ = proc.info.get('environ') or {}
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                
                # Check by SteamAppId or SteamGameId in environment
                if (environ.get('SteamAppId') == app_id or 
                    environ.get('SteamGameId') == app_id or
                    f"SteamAppId={app_id}" in cmdline or
                    f"SteamGameId={app_id}" in cmdline):
                    
                    wineserver_pid = None
                    for child in psutil.Process(proc.info['pid']).children(recursive=True):
                        if child.name() == 'wineserver':
                            wineserver_pid = child.pid
                            break
                    
                    return {
                        'linux_pid': proc.info['pid'],
                        'wine_pid': proc.info['pid'],
                        'wineserver_pid': None,  # Will be found via prefix if needed
                        'cmdline': cmdline[:200],
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
    except ImportError:
        pass
    
    return None


def find_all_wineservers() -> List[Dict[str, Any]]:
    """Find all running wineservers with their prefixes."""
    wineservers = []
    
    if not PSUTIL_AVAILABLE:
        return wineservers
    
    try:
        for proc in psutil.process_iter(['pid', 'environ']):
            try:
                environ = proc.info.get('environ') or {}
                prefix = environ.get('WINEPREFIX')
                if prefix:
                    wineservers.append({
                        'pid': proc.info['pid'],
                        'prefix': prefix,
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
    except ImportError:
        pass
    
    return wineservers


def find_wineserver_for_prefix(prefix_path: Path) -> Optional[int]:
    """Find wineserver PID for a specific prefix."""
    prefix_str = str(prefix_path)

    if PSUTIL_AVAILABLE:
        try:
            # Fetch name, pid, and environ
            for proc in psutil.process_iter(['pid', 'name', 'environ']):
                try:
                    environ = proc.info.get('environ') or {}
                    if environ.get('WINEPREFIX') == prefix_str and proc.info.get('name') == 'wineserver':
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
                if f"WINEPREFIX={prefix_str}" in environ_data:
                    return pid
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return None


def copy_wineserver_env(wineserver_pid: int) -> Dict[str, str]:
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


def find_game_processes_for_trainer(game_prefix: Path, game_appid: str) -> List[Dict[str, Any]]:
    """Find all potential game processes that a trainer could hook into."""
    processes = []
    
    # 1. By prefix (most reliable)
    by_prefix = find_game_process_by_prefix(game_prefix)
    if by_prefix:
        processes.append({**by_prefix, 'match_type': 'prefix'})
    
    # 2. By AppId
    by_appid = find_game_process_by_appid(game_appid)
    if by_appid:
        processes.append({**by_appid, 'match_type': 'appid'})
    
    # 3. All wineservers for this prefix
    for ws in find_all_wineservers():
        if ws['prefix'] == str(game_prefix):
            processes.append({
                'wineserver_pid': ws['pid'],
                'match_type': 'wineserver',
            })
    
    return processes


def get_best_trainer_target(game_prefix: Path, game_appid: str) -> Optional[Dict[str, Any]]:
    """Get the best target process for trainer injection."""
    processes = find_game_processes_for_trainer(game_prefix, game_appid)
    
    if not processes:
        return None
    
    # Priority: prefix match > appid match > wineserver only
    priority = {'prefix': 3, 'appid': 2, 'wineserver': 1}
    processes.sort(key=lambda p: priority.get(p.get('match_type', ''), 0), reverse=True)
    
    return processes[0] if processes else None