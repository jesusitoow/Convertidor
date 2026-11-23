"""Clasificación de descargas y saneamiento seguro de nombres de carpeta.

Este módulo es puro (no toca red ni interfaz): recibe metadatos de ``yt-dlp`` y
devuelve el nombre de la carpeta destino. Toda cadena que vaya a formar parte de
una ruta pasa por :func:`sanitize_component`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# --------------------------------------------------------------------------- enums


class DownloadMode(StrEnum):
    """Tipo de descarga soportado por el motor."""

    AUDIO = "audio"
    VIDEO = "video"


class OrganizeMode(StrEnum):
    """Modos de organización disponibles en la interfaz."""

    ARTIST = "artist"
    GENRE = "genre"
    GENRE_ARTIST = "genre_artist"
    FLAT = "flat"


class VideoQuality(StrEnum):
    """Selector de calidad de vídeo."""

    MAX = "max"
    P1080 = "1080"
    P720 = "720"


class Platform(StrEnum):
    """Plataforma detectada a partir de la URL."""

    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    OTHER = "other"


# ------------------------------------------------------------------------- constantes

YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }
)
TIKTOK_HOSTS = frozenset(
    {
        "tiktok.com",
        "www.tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
        "m.tiktok.com",
    }
)

DOWNLOAD_LABELS: dict[DownloadMode, str] = {
    DownloadMode.AUDIO: "Audio (MP3 · 320 kbps)",
    DownloadMode.VIDEO: "Video (MP4 · Máxima calidad)",
}
ORGANIZE_LABELS: dict[OrganizeMode, str] = {
    OrganizeMode.ARTIST: "Por Artista",
    OrganizeMode.GENRE: "Por Género",
    OrganizeMode.GENRE_ARTIST: "Género + Artista",
    OrganizeMode.FLAT: "Directo",
}
VIDEO_QUALITY_LABELS: dict[VideoQuality, str] = {
    VideoQuality.MAX: "Máxima disponible (4K/1080p)",
    VideoQuality.P1080: "1080p",
    VideoQuality.P720: "720p",
}

GENRES = (
    "Salsa",
    "Vallenato",
    "Afro - Afrobeats",
    "Urbano - Reggaeton",
    "Pop",
    "Rock",
    "Electronica",
    "Otros",
)
GENRE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Salsa": ("salsa", "son cubano", "timba"),
    "Vallenato": ("vallenato", "vallenata", "cumbia", "merengue"),
    "Afro - Afrobeats": ("afrobeat", "afrobeats", "afro", "amapiano", "highlife"),
    "Urbano - Reggaeton": (
        "reggaeton",
        "reggaetón",
        "urbano",
        "trap",
        "dembow",
        "latin trap",
        "perreo",
        "bad bunny",
        "niche",
    ),
    "Pop": ("pop", "k-pop", "synthpop"),
    "Rock": ("rock", "metal", "indie", "punk", "alternativa"),
    "Electronica": ("electronica", "electrónica", "edm", "house", "techno", "dance", "dj"),
}
DEFAULT_GENRE = "Otros"
DEFAULT_ARTIST = "Otros"

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_DOTS = re.compile(r"\.{2,}")
_WHITESPACE = re.compile(r"\s+")
_RESERVED_WINDOWS = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)
_ARTIST_KEYS = ("artist", "uploader", "channel", "creator", "author", "account")
_GENRE_KEYS = ("genre", "tags", "categories", "category", "title", "description")


# ---------------------------------------------------------------------------- textos


def _fold(text: str) -> str:
    """Minúsculas sin acentos, apto para comparar etiquetas."""

    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def _contains(text: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(_fold(keyword))}\b", _fold(text)) is not None


def sanitize_component(value: str | None, fallback: str = DEFAULT_GENRE, max_length: int = 80) -> str:
    """Devuelve un componente de ruta seguro para Windows, macOS y Linux.

    Elimina caracteres prohibidos por Windows (``\\ / : * ? " < > |``), puntos
    consecutivos (``..``), controladores reservados (``CON``, ``NUL``, ...) y
    espacios/puntos finales. Nunca devuelve un separador de ruta.
    """

    if not value or not isinstance(value, str):
        return fallback
    text = value.replace("\u200b", "").strip()
    text = _FORBIDDEN.sub(" ", text)
    text = _DOTS.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip(" .")
    text = text[:max_length].strip(" .")
    if not text:
        return fallback
    stem = text.split(".", 1)[0].rstrip(" .").upper()
    if stem in _RESERVED_WINDOWS:
        return f"_{text}"
    return text


def genre_from_text(text: str | None) -> str:
    """Clasifica un texto libre en una de las categorías musicales conocidas."""

    if not text:
        return DEFAULT_GENRE
    for genre, keywords in GENRE_KEYWORDS.items():
        if any(_contains(text, keyword) for keyword in keywords):
            return genre
    return DEFAULT_GENRE


def _first_text(metadata: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            joined = ", ".join(str(item) for item in value if item)
            if joined.strip():
                return joined
    return ""


def artist_name(metadata: Mapping[str, Any]) -> str:
    """Extrae el artista/creador de los metadatos de ``yt-dlp``."""

    return sanitize_component(_first_text(metadata, _ARTIST_KEYS), fallback=DEFAULT_ARTIST)


def genre_name(metadata: Mapping[str, Any], manual_genre: str | None = None) -> str:
    """Género final: el texto manual manda; si no, se infiere de los metadatos.

    Si el usuario escribe un género reconocible (``reggaeton``, ``salsa``, ...)
    se normaliza a la carpeta canónica. Si escribe otro texto se respeta como
    carpeta personalizada, siempre sanitizado.
    """

    manual = sanitize_component(manual_genre, fallback="") if manual_genre else ""
    if manual:
        canonical = genre_from_text(manual)
        if canonical != DEFAULT_GENRE:
            return canonical
        if _fold(manual) in {_fold(genre) for genre in GENRES}:
            return next(genre for genre in GENRES if _fold(genre) == _fold(manual))
        return manual
    source = _first_text(metadata, _GENRE_KEYS)
    return genre_from_text(source)


# ----------------------------------------------------------------------------- URLs


def _hostname(url: str) -> str:
    try:
        host = urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""
    return host.rstrip(".").casefold()


def detect_platform(url: str) -> Platform:
    """Detecta YouTube, TikTok u otra plataforma a partir del host."""

    host = _hostname(url)
    if host in YOUTUBE_HOSTS:
        return Platform.YOUTUBE
    if host in TIKTOK_HOSTS:
        return Platform.TIKTOK
    return Platform.OTHER


# ------------------------------------------------------------------------- destinos


def resolve_destination(
    base: Path,
    mode: OrganizeMode | str,
    metadata: Mapping[str, Any] | None = None,
    manual_genre: str | None = None,
    platform: Platform | None = None,
) -> Path:
    """Calcula (y crea) la carpeta destino según el modo de organización.

    Ejemplos::

        resolve_destination(musica, "artist", {"artist": "Bad Bunny"})
        # ~/Downloads/Musica/Bad Bunny

        resolve_destination(musica, "genre_artist", {"genre": "reggaeton", "artist": "Bad Bunny"})
        # ~/Downloads/Musica/Urbano - Reggaeton/Bad Bunny
    """

    organization = OrganizeMode(mode)
    info = dict(metadata or {})
    if platform is not None:
        info.setdefault("platform", platform.value)

    root = Path(base).expanduser().resolve()
    parts: list[str] = []
    if organization is OrganizeMode.GENRE or organization is OrganizeMode.GENRE_ARTIST:
        parts.append(genre_name(info, manual_genre))
    if organization is OrganizeMode.ARTIST or organization is OrganizeMode.GENRE_ARTIST:
        parts.append(artist_name(info))

    target = root.joinpath(*parts)
    if target != root and root not in target.parents:
        raise ValueError("La carpeta destino queda fuera de la carpeta base")
    target.mkdir(parents=True, exist_ok=True)
    return target
