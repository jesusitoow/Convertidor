"""Biblioteca de archivos: escaneo recursivo, apertura segura y borrado a papelera.

Solo se exponen funciones de sistema de archivos; ninguna dependencia de GUI.
Las rutas se validan con ``resolve()`` antes de cualquier operación destructiva.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

try:
    from send2trash import send2trash as _send2trash
except ImportError:  # la papelera es opcional en tiempo de ejecución
    _send2trash = None

TRACK_SUFFIX = ".mp3"
VIDEO_SUFFIX = ".mp4"
LEFTOVER_SUFFIXES = (".part", ".ytdl", ".temp")
_MEDIA_SUFFIXES = {TRACK_SUFFIX, VIDEO_SUFFIX}
_DELETABLE_SUFFIXES = _MEDIA_SUFFIXES | set(LEFTOVER_SUFFIXES)


class MediaKind(StrEnum):
    """Tipo de archivo mostrado en la biblioteca."""

    AUDIO = "MP3"
    VIDEO = "MP4"


@dataclass(frozen=True, slots=True)
class MediaFile:
    """Un archivo de la biblioteca, con su categoría ya calculada."""

    path: Path
    size: int
    mtime: float
    kind: MediaKind
    category: str
    source: str

    @property
    def name(self) -> str:
        return self.path.stem


def trash_available() -> bool:
    """Indica si se puede enviar a la papelera del sistema."""

    return _send2trash is not None


def human_size(num: float) -> str:
    """Formatea bytes como B / KB / MB / GB."""

    value = max(0.0, float(num))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _walk_files(folder: Path) -> Iterable[Path]:
    if not folder.is_dir():
        return ()
    return (path for path in folder.rglob("*") if path.is_file() and not path.is_symlink())


def _category(path: Path, root: Path) -> str:
    relative = path.parent.relative_to(root).as_posix()
    return "Directo" if relative == "." else relative


def list_media(*folders: Path) -> list[MediaFile]:
    """Escanea recursivamente todas las carpetas indicadas.

    En ``Musica`` solo se listan MP3 y en ``Videos`` solo MP4; el nombre es
    indistinto para la función, así que se infiere del sufijo real.
    """

    media: list[MediaFile] = []
    for folder in folders:
        root = Path(folder).expanduser()
        for path in _walk_files(root):
            suffix = path.suffix.lower()
            if suffix not in _MEDIA_SUFFIXES:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            media.append(
                MediaFile(
                    path=path,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    kind=MediaKind.AUDIO if suffix == TRACK_SUFFIX else MediaKind.VIDEO,
                    category=_category(path, root),
                    source=root.name,
                )
            )
    return sorted(media, key=lambda item: item.mtime, reverse=True)


def list_leftovers(*folders: Path) -> list[Path]:
    """Restos de descargas interrumpidas dentro de las carpetas indicadas."""

    found: list[Path] = []
    for folder in folders:
        for path in _walk_files(Path(folder).expanduser()):
            if path.suffix.lower() in LEFTOVER_SUFFIXES:
                found.append(path)
    return sorted(found)


def delete_files(
    paths: Iterable[Path],
    roots: Iterable[Path],
    use_trash: bool = True,
) -> tuple[int, list[str]]:
    """Elimina archivos dentro de ``roots``. Devuelve ``(borrados, errores)``.

    Con ``use_trash`` se usa la papelera; si no está disponible se informa del
    error en lugar de borrar permanentemente. Nunca se siguen enlaces
    simbólicos ni se tocan archivos fuera de las carpetas base.
    """

    allowed_roots = tuple(Path(root).expanduser().resolve() for root in roots)
    deleted = 0
    errors: list[str] = []
    for path in paths:
        original = Path(path).expanduser()
        try:
            if original.is_symlink():
                errors.append(f"{original.name}: enlaces simbólicos no permitidos")
                continue
            real = original.resolve()
            if not any(real.is_relative_to(root) for root in allowed_roots):
                errors.append(f"{original.name}: fuera de la carpeta permitida")
                continue
            if real.suffix.lower() not in _DELETABLE_SUFFIXES or not real.is_file():
                errors.append(f"{original.name}: tipo de archivo no permitido")
                continue
            if use_trash:
                if _send2trash is None:
                    errors.append(f"{original.name}: papelera no disponible")
                    continue
                _send2trash(str(real))
            else:
                real.unlink()
            deleted += 1
        except Exception as exc:  # noqa: BLE001 - se informa y se continúa
            errors.append(f"{original.name}: {exc}")
    return deleted, errors


def open_path(path: Path) -> None:
    """Abre un archivo o carpeta con la aplicación predeterminada del sistema."""

    target = Path(path).expanduser()
    if not target.exists():
        raise FileNotFoundError(str(target))
    if sys.platform.startswith("win"):
        os.startfile(str(target))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_containing_folder(path: Path) -> None:
    """Abre la carpeta que contiene un archivo."""

    open_path(Path(path).expanduser().parent)
