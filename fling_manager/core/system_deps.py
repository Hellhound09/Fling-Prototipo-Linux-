"""Instalación de dependencias de sistema 32-bit (pacman + yay AUR automático)."""

import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Callable
import logging

from .sudo_helper import SudoHelper

logger = logging.getLogger(__name__)

# Dependencias 32-bit en repos oficiales Arch/CachyOS
OFFICIAL_DEPS_32BIT = [
    # Gráficos/Vulkan
    'lib32-vkd3d',
    'lib32-vulkan-icd-loader',
    'lib32-mesa',
    'lib32-glu',
    # Multimedia/Audio
    'lib32-faudio',
    'lib32-openal',
    'lib32-mpg123',
    'lib32-gstreamer',
    'lib32-gst-plugins-base',
    'lib32-gst-plugins-good',
    # Sistema base
    'lib32-gnutls',
    'lib32-libldap',
    'lib32-freetype2',
    'lib32-libpng',
    'lib32-libjpeg-turbo',
    'lib32-sqlite',
    'lib32-libusb',
    'lib32-alsa-lib',
    'lib32-pulseaudio',
]

# Drivers GPU específicos (se añaden según detección)
GPU_DEPS = {
    "nvidia": ['lib32-nvidia-utils'],
    "amd": ['lib32-vulkan-radeon', 'lib32-ati-dri'],
    "intel": ['lib32-vulkan-intel', 'lib32-intel-media-driver'],
}


class SystemDepsManager:
    """Gestiona instalación de dependencias 32-bit del sistema."""

    def __init__(self, parent_window=None):
        self.parent_window = parent_window
        self.sudo_helper = SudoHelper(parent_window)

    def _detect_gpu(self) -> str:
        """Detecta vendor GPU via lspci."""
        try:
            out = subprocess.run(
                ['lspci', '-d', '::0300', '-mm'],
                capture_output=True, text=True, timeout=5
            ).stdout.lower()
            
            if 'nvidia' in out:
                return "nvidia"
            if 'amd' in out or 'ati' in out:
                return "amd"
            if 'intel' in out:
                return "intel"
        except Exception:
            pass
        return "unknown"

    def get_required_packages(self) -> List[str]:
        """Obtiene lista completa de paquetes necesarios según GPU."""
        gpu = self._detect_gpu()
        pkgs = OFFICIAL_DEPS_32BIT.copy()
        pkgs.extend(GPU_DEPS.get(gpu, []))
        return pkgs

    def install(self, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Instala todas las dependencias 32-bit necesarias.
        - Actualiza DB pacman
        - Instala paquetes oficiales
        - Instala paquetes AUR si hay yay/paru
        """
        packages = self.get_required_packages()

        if progress_callback:
            progress_callback("Actualizando base de datos de paquetes...")

        # 1. Actualizar DB
        success, output = self._run_pacman_sy()
        if not success:
            return False, f"Fallo actualizando DB pacman: {output}"

        # 2. Verificar qué falta
        missing = []
        for pkg in packages:
            try:
                subprocess.run(['pacman', '-Q', pkg], capture_output=True, timeout=5, check=True)
            except subprocess.CalledProcessError:
                missing.append(pkg)

        if not missing:
            return True, "Todas las dependencias 32-bit ya instaladas"

        # 3. Separar oficiales vs AUR
        official_missing = []
        aur_missing = []
        for pkg in missing:
            try:
                subprocess.run(['pacman', '-Si', pkg], capture_output=True, timeout=5, check=True)
                official_missing.append(pkg)
            except subprocess.CalledProcessError:
                aur_missing.append(pkg)

        # 4. Instalar oficiales
        if official_missing:
            if progress_callback:
                progress_callback(f"Instalando {len(official_missing)} paquetes 32-bit (repos oficiales)...")
            
            success, output = self._run_pacman_install(official_missing)
            if not success:
                return False, f"Fallo instalando paquetes oficiales: {output}"

        # 5. AUR - detectar yay/paru e instalar
        if aur_missing:
            aur_helper = self._find_aur_helper()
            if aur_helper:
                if progress_callback:
                    progress_callback(f"Instalando {len(aur_missing)} paquetes AUR con {aur_helper}...")
                
                success, output = self._run_aur_install(aur_helper, aur_missing)
                if not success:
                    return True, f"Oficiales OK. AUR falló: {output}. Instale manualmente: {aur_helper} -S {' '.join(aur_missing)}"
            else:
                return True, f"Oficiales OK. AUR pendiente (instale yay/paru): {', '.join(aur_missing)}"

        return True, f"Dependencias 32-bit instaladas correctamente"

    def _run_pacman_sy(self) -> Tuple[bool, str]:
        """Ejecuta pacman -Sy usando sudo con GUI."""
        return self.sudo_helper.run_with_sudo(
            ['pacman', '-Sy'],
            prompt_message="Actualizando base de datos de paquetes...",
            timeout=60  # 1 minuto para actualizar DB
        )

    def _run_pacman_install(self, packages: List[str]) -> Tuple[bool, str]:
        """Instala paquetes con pacman usando sudo con GUI."""
        cmd = ['pacman', '-S', '--needed', '--noconfirm'] + packages
        return self.sudo_helper.run_with_sudo(
            cmd,
            prompt_message=f"Instalando {len(packages)} paquetes 32-bit (repos oficiales)...",
            timeout=300  # 5 minutos para instalaciones
        )

    def _find_aur_helper(self) -> Optional[str]:
        """Detecta yay o paru"""
        for helper in ['yay', 'paru']:
            try:
                subprocess.run(['which', helper], capture_output=True, check=True)
                return helper
            except subprocess.CalledProcessError:
                continue
        return None

    def _run_aur_install(self, helper: str, packages: List[str]) -> Tuple[bool, str]:
        """Instala paquetes AUR"""
        try:
            cmd = [helper, '-S', '--needed', '--noconfirm'] + packages
            # AUR helpers no necesitan sudo, lo manejan internamente
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)