"""Validación de URLs y motor de descarga (yt-dlp + FFmpeg), sin dependencias de UI."""

from __future__ import annotations

import ipaddress
import re
import shutil
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yt_dlp

from .config import AUDIO_QUALITIES
from .library import human_size
from .organizer import (
    TIKTOK_HOSTS,
    YOUTUBE_HOSTS,
    DownloadMode,
    Platform,
    VideoQuality,
    detect_platform,
)

# YOUTUBE_HOSTS / TIKTOK_HOSTS se reexportan desde organizer para evitar duplicar la lista.
# Otras plataformas públicas soportadas por yt-dlp: se admiten subdominios.
OTHER_PLATFORM_DOMAINS = (
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "x.com",
    "twitter.com",
    "soundcloud.com",
    "vimeo.com",
)
_LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".test")
_ALLOWED_PORTS = frozenset({None, 80, 443})
_HOST_RE = re.compile(r"^[a-z0-9.-]+$")


class DownloadCancelled(Exception):
    """El usuario canceló la descarga."""


class UnsupportedURLError(ValueError):
    """La URL no es válida o no pertenece a una plataforma permitida."""


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    """Todo lo necesario para ejecutar una descarga."""

    url: str
    destination: Path
    mode: DownloadMode = DownloadMode.AUDIO
    audio_quality: str = "320"
    video_quality: str = VideoQuality.MAX.value
    playlist: bool = False

    @property
    def platform(self) -> Platform:
        return detect_platform(self.url)


# ---------------------------------------------------------------------- validación


def _normalize_host(host: str) -> str:
    cleaned = host.rstrip(".").casefold()
    if not cleaned:
        return ""
    try:
        ascii_host = cleaned.encode("idna").decode("ascii").casefold()
    except UnicodeError:
        return ""
    return ascii_host if _HOST_RE.fullmatch(ascii_host) else ""


def _is_blocked_host(host: str) -> bool:
    """Bloquea IP privadas, hosts locales y nombres de una sola etiqueta."""

    if host in {"localhost", "localhost.localdomain"} or host.endswith(_LOCAL_SUFFIXES):
        return True
    if "." not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    # is_global ya cubre privadas, loopback, link-local, reservadas y multicast.
    return not address.is_global


def _is_other_platform_host(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in OTHER_PLATFORM_DOMAINS)


def is_supported_url(value: str) -> bool:
    """Valida esquema, host y plataforma antes de pasar la URL a yt-dlp.

    Acepta solo ``http``/``https`` de dominios públicos conocidos. Rechaza
    ``file://``, ``javascript:``, ``ftp://``, IPs privadas, ``localhost``,
    credenciales embebidas, puertos no estándar y URLs malformadas.
    """

    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > 2048 or any(ord(char) < 32 or ord(char) == 127 for char in text):
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    if parts.scheme.casefold() not in {"http", "https"}:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    try:
        port = parts.port
    except ValueError:
        return False
    if port not in _ALLOWED_PORTS:
        return False

    host = _normalize_host(parts.hostname or "")
    if not host or _is_blocked_host(host):
        return False

    platform = detect_platform(text)
    if platform is Platform.YOUTUBE:
        return host in YOUTUBE_HOSTS
    if platform is Platform.TIKTOK:
        return host in TIKTOK_HOSTS
    return _is_other_platform_host(host)


def is_youtube_url(value: str) -> bool:
    """Helper de compatibilidad: ``True`` solo para URLs de YouTube seguras."""

    return is_supported_url(value) and detect_platform(value) is Platform.YOUTUBE


def is_tiktok_url(value: str) -> bool:
    """``True`` solo para URLs de TikTok seguras."""

    return is_supported_url(value) and detect_platform(value) is Platform.TIKTOK


def find_ffmpeg() -> str | None:
    """FFmpeg del sistema; si no hay, el binario de ``imageio-ffmpeg``."""

    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001 - dependencia opcional en tiempo de ejecución
        return None


# ------------------------------------------------------------------------ opciones


def _video_format(video_quality: str) -> str:
    quality = VideoQuality(video_quality)
    if quality is VideoQuality.P1080:
        return "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    if quality is VideoQuality.P720:
        return "bestvideo[height<=720]+bestaudio/best[height<=720]"
    return "bestvideo+bestaudio/best"


def build_options(
    dest: Path,
    mode: DownloadMode | str = DownloadMode.AUDIO,
    audio_quality: str = "320",
    video_quality: str = VideoQuality.MAX.value,
    playlist: bool = False,
    ffmpeg: str | None = None,
    hook: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Construye las opciones de ``yt-dlp`` para audio o vídeo."""

    download_mode = DownloadMode(mode)
    if audio_quality not in AUDIO_QUALITIES:
        audio_quality = "320"
    if video_quality not in tuple(quality.value for quality in VideoQuality):
        video_quality = VideoQuality.MAX.value

    options: dict[str, Any] = {
        "outtmpl": str(Path(dest).expanduser() / "%(title)s.%(ext)s"),
        "noplaylist": not playlist,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
    }
    if ffmpeg:
        options["ffmpeg_location"] = ffmpeg
    if hook:
        options["progress_hooks"] = [hook]

    if download_mode is DownloadMode.AUDIO:
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": audio_quality},
            {"key": "FFmpegMetadata", "add_metadata": True},
        ]
    else:
        options["format"] = _video_format(video_quality)
        options["merge_output_format"] = "mp4"
        options["postprocessors"] = [{"key": "FFmpegMetadata", "add_metadata": True}]
        # No se fuerza ningún extractor de terceros: los extractores nativos de
        # yt-dlp para TikTok priorizan `play_addr` (sin marca de agua) sobre
        # `download_addr` (marcado como watermarked) cuando está disponible.
    return options


def fetch_metadata(url: str, ffmpeg: str | None = None, playlist: bool = False) -> dict[str, Any]:
    """Obtiene título, artista y género antes de elegir la carpeta destino."""

    if not is_supported_url(url):
        raise UnsupportedURLError(url)
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": not playlist,
        "windowsfilenames": True,
    }
    if ffmpeg:
        options["ffmpeg_location"] = ffmpeg
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    return dict(info) if isinstance(info, Mapping) else {}


def _progress_hook(
    data: dict[str, Any],
    cancel: threading.Event | None,
    on_progress: Callable[[float, str], None] | None,
    on_title: Callable[[str], None] | None,
    on_convert: Callable[[], None] | None,
) -> None:
    if cancel is not None and cancel.is_set():
        raise DownloadCancelled()

    info = data.get("info_dict")
    if isinstance(info, Mapping):
        title = info.get("title")
        if isinstance(title, str) and title and on_title:
            on_title(title)

    status = data.get("status")
    if status == "downloading" and on_progress:
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded = data.get("downloaded_bytes") or 0
        if isinstance(total, (int, float)) and total > 0 and isinstance(downloaded, (int, float)):
            speed = data.get("speed")
            detail = f"{human_size(float(speed))}/s" if isinstance(speed, (int, float)) and speed else ""
            on_progress(float(downloaded) / float(total), detail)
    elif status in {"finished", "postprocessing"} and on_convert:
        on_convert()


def download(
    request: DownloadRequest,
    *,
    ffmpeg: str | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    on_title: Callable[[str], None] | None = None,
    on_convert: Callable[[], None] | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Descarga y convierte una URL. Lanza ``DownloadCancelled`` si se cancela."""

    if not is_supported_url(request.url):
        raise UnsupportedURLError(request.url)
    if cancel is not None and cancel.is_set():
        raise DownloadCancelled()
    Path(request.destination).expanduser().mkdir(parents=True, exist_ok=True)

    def hook(data: dict[str, Any]) -> None:
        _progress_hook(data, cancel, on_progress, on_title, on_convert)

    options = build_options(
        request.destination,
        request.mode,
        request.audio_quality,
        request.video_quality,
        request.playlist,
        ffmpeg,
        hook,
    )
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.extract_info(request.url, download=True)
