"""Ajustes persistentes en ``~/.yt2mp3/config.json`` (tolerante a fallos)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .organizer import OrganizeMode, VideoQuality

log = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".yt2mp3"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_MUSIC_FOLDER = Path.home() / "Downloads" / "Musica"
DEFAULT_VIDEO_FOLDER = Path.home() / "Downloads" / "Videos"

AUDIO_QUALITIES = ("320", "192", "128")
APPEARANCES = ("dark", "light", "system")
VIDEO_QUALITIES = tuple(quality.value for quality in VideoQuality)
ORGANIZE_MODES = tuple(mode.value for mode in OrganizeMode)

# Compatibilidad con la configuración de la v1 (claves antiguas -> nuevas).
_LEGACY_KEYS: dict[str, str] = {
    "folder": "music_folder",
    "quality": "audio_quality",
}


@dataclass(slots=True)
class Settings:
    """Estado de la aplicación, serializable como JSON.

    Los valores por defecto son universales: ``Path.home()`` funciona en
    Windows, macOS y Linux sin rutas cableadas.
    """

    music_folder: str = str(DEFAULT_MUSIC_FOLDER)
    video_folder: str = str(DEFAULT_VIDEO_FOLDER)
    audio_quality: str = "320"
    video_quality: str = VideoQuality.MAX.value
    organize_mode: str = OrganizeMode.ARTIST.value
    appearance: str = "dark"
    auto_download: bool = True
    playlist: bool = False
    legal_accepted: bool = False

    @property
    def music_path(self) -> Path:
        return Path(self.music_folder).expanduser()

    @property
    def video_path(self) -> Path:
        return Path(self.video_folder).expanduser()

    @property
    def folders(self) -> tuple[Path, Path]:
        return self.music_path, self.video_path

    def ensure_folders(self) -> tuple[Path, Path]:
        """Crea ambas carpetas base si no existen y las devuelve."""

        music, video = self.folders
        for folder in (music, video):
            folder.mkdir(parents=True, exist_ok=True)
        return music, video

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> Settings:
        """Lee los ajustes; si no existen o están dañados usa los valores por defecto."""

        settings = cls()
        try:
            raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return settings
        except (OSError, ValueError, UnicodeError) as exc:
            log.warning("No se pudo leer %s (%s). Se usan valores por defecto.", path, exc)
            return settings

        if not isinstance(raw, dict):
            return settings

        known = {field.name for field in fields(cls)}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            name = _LEGACY_KEYS.get(key, key)
            if name not in known:
                continue
            expected = type(getattr(settings, name))
            if not isinstance(value, expected):
                continue
            setattr(settings, name, value)

        settings.audio_quality = settings.audio_quality if settings.audio_quality in AUDIO_QUALITIES else "320"
        settings.video_quality = (
            settings.video_quality if settings.video_quality in VIDEO_QUALITIES else VideoQuality.MAX.value
        )
        settings.organize_mode = (
            settings.organize_mode if settings.organize_mode in ORGANIZE_MODES else OrganizeMode.ARTIST.value
        )
        settings.appearance = settings.appearance if settings.appearance in APPEARANCES else "dark"
        if not settings.music_folder.strip():
            settings.music_folder = str(DEFAULT_MUSIC_FOLDER)
        if not settings.video_folder.strip():
            settings.video_folder = str(DEFAULT_VIDEO_FOLDER)
        return settings

    def save(self, path: Path = CONFIG_FILE) -> None:
        """Guarda de forma atómica; un fallo de disco nunca rompe la app."""

        target = Path(path)
        temporary = target.with_name(f"{target.name}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(target)
        except (OSError, TypeError, ValueError) as exc:
            log.warning("No se pudieron guardar los ajustes en %s: %s", target, exc)
