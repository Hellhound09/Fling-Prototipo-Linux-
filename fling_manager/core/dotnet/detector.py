"""Detección robusta de .NET 4.8 en prefijos Wine."""

import subprocess
from pathlib import Path
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# Versiones .NET 4.x por Release key
DOTNET_RELEASE_VERSIONS = {
    0x82348: "4.8",      # 528840
    0x82347: "4.8",      # 528839
    0x82346: "4.8",      # 528838
    0x82345: "4.8",      # 528837
    0x82344: "4.8",      # 528836
    0x82343: "4.8",      # 528835
    0x82342: "4.8",      # 528834
    0x82341: "4.8",      # 528833
    0x82340: "4.8",      # 528832
    0x80EB1: "4.7.2",    # 527793
    0x80EB0: "4.7.2",    # 527792
    0x7E33C: "4.7.1",    # 517180
    0x7E33B: "4.7.1",    # 517179
    0x7E33A: "4.7.1",    # 517178
    0x7D4C2: "4.7",      # 515906
    0x7D4C1: "4.7",      # 515905
    0x7D4C0: "4.7",      # 515904
}

DOTNET48_MIN_RELEASE = 0x82340  # 4.8 RTM minimum


class DotNetDetector:
    """Detector robusto de .NET 4.8 en prefijos Wine."""

    def __init__(self, prefix_path: Path):
        self.prefix_path = Path(prefix_path)
        self.wine_bin = self._find_wine_bin()

    def _find_wine_bin(self) -> Optional[Path]:
        """Busca wine en el sistema."""
        candidates = [
            Path("/usr/bin/wine"),
            Path("/usr/local/bin/wine"),
            Path.home() / ".local/bin/wine",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def is_dotnet48_installed(self) -> Tuple[bool, str]:
        """
        Verifica si .NET 4.8 está instalado correctamente.
        
        Returns:
            (bool, str): (instalado, detalles)
        """
        checks = []
        
        # 1. Verificar registry Release key
        release_ok, release_val = self._check_release_key()
        checks.append(("Registry Release >= 0x82340", release_ok, f"Release=0x{release_val:X}" if release_val else "No encontrado"))
        
        # 2. Verificar mscorlib.dll > 1MB en Framework64
        mscorlib_ok, mscorlib_size = self._check_mscorlib_64()
        checks.append(("mscorlib.dll 64-bit > 1MB", mscorlib_ok, f"{mscorlib_size} bytes" if mscorlib_size else "No encontrado"))
        
        # 3. Verificar ngen.exe funcional
        ngen_ok, ngen_path = self._check_ngen()
        checks.append(("ngen.exe funcional", ngen_ok, str(ngen_path) if ngen_ok else "No funcional"))
        
        # 4. Verificar clr.dll
        clr_ok, clr_path = self._check_clr()
        checks.append(("clr.dll presente", clr_ok, str(clr_path) if clr_ok else "No encontrado"))
        
        # Resumen
        all_ok = all(c[1] for c in checks)
        details = "; ".join([f"{c[0]}: {'OK' if c[1] else 'FAIL'} ({c[2]})" for c in checks])
        
        return all_ok, details

    def _check_release_key(self) -> Tuple[bool, Optional[int]]:
        """Verifica HKLM\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full\\Release"""
        if not self.wine_bin:
            return False, None
        
        try:
            result = subprocess.run([
                str(self.wine_bin), 'reg', 'query',
                'HKLM\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full',
                '/v', 'Release'
            ], capture_output=True, text=True, timeout=10, errors='replace')
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'Release' in line and 'REG_DWORD' in line:
                        parts = line.split()
                        for part in parts:
                            if part.startswith('0x'):
                                return int(part, 16) >= DOTNET48_MIN_RELEASE, int(part, 16)
        except Exception as e:
            logger.debug(f"Error checking Release key: {e}")
        
        return False, None

    def _check_mscorlib_64(self) -> Tuple[bool, Optional[int]]:
        """Verifica mscorlib.dll en Framework64 > 1MB"""
        mscorlib_path = self.prefix_path / "drive_c" / "windows" / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "mscorlib.dll"
        
        if mscorlib_path.exists():
            size = mscorlib_path.stat().st_size
            return size > 1000000, size
        
        return False, None

    def _check_ngen(self) -> Tuple[bool, Optional[Path]]:
        """Verifica ngen.exe funcional"""
        ngen_path = self.prefix_path / "drive_c" / "windows" / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "ngen.exe"
        
        if ngen_path.exists():
            size = ngen_path.stat().st_size
            if size > 10000:
                return True, ngen_path
        
        # También buscar en Framework (32-bit)
        ngen_path_32 = self.prefix_path / "drive_c" / "windows" / "Microsoft.NET" / "Framework" / "v4.0.30319" / "ngen.exe"
        if ngen_path_32.exists():
            size = ngen_path_32.stat().st_size
            if size > 10000:
                return True, ngen_path_32
        
        return False, None

    def _check_clr(self) -> Tuple[bool, Optional[Path]]:
        """Verifica clr.dll en Framework64"""
        clr_path = self.prefix_path / "drive_c" / "windows" / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "clr.dll"
        
        if clr_path.exists() and clr_path.stat().st_size > 10000:
            return True, clr_path
        
        return False, None

    def get_installed_version(self) -> Optional[str]:
        """Obtiene la versión instalada basada en Release key"""
        if not self.wine_bin:
            return None
        
        try:
            result = subprocess.run([
                str(self.wine_bin), 'reg', 'query',
                'HKLM\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full',
                '/v', 'Release'
            ], capture_output=True, text=True, timeout=10, errors='replace')
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'Release' in line and 'REG_DWORD' in line:
                        parts = line.split()
                        for part in parts:
                            if part.startswith('0x'):
                                release = int(part, 16)
                                return DOTNET_RELEASE_VERSIONS.get(release, f"4.x (Release=0x{release:X})")
        except Exception:
            pass
        
        return None