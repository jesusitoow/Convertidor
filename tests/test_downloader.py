"""Pruebas de validación de URLs y construcción/ejecución del motor de descarga."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Literal

import pytest
import yt_dlp

from yt2mp3.downloader import (
    DownloadCancelled,
    DownloadRequest,
    UnsupportedURLError,
    build_options,
    download,
    fetch_metadata,
    find_ffmpeg,
    is_supported_url,
    is_tiktok_url,
    is_youtube_url,
)
from yt2mp3.organizer import DownloadMode


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "http://youtube.com/watch?v=abc",
        "https://m.youtube.com/watch?v=abc",
        "https://music.youtube.com/watch?v=abc",
        "https://youtu.be/dQw4w9WgXcQ",
        "  https://vm.tiktok.com/Zabc/  ",
        "https://vt.tiktok.com/Zabc/",
        "https://www.tiktok.com/@user/video/123",
        "https://www.instagram.com/reel/abc/",
        "https://x.com/user/status/123",
        "https://soundcloud.com/user/track",
        "https://vimeo.com/123",
    ],
)
def test_supported_urls(url: str) -> None:
    assert is_supported_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "youtube.com/watch?v=abc",
        "https://evil.com/?u=youtube.com",
        "https://youtube.com.evil.com/watch",
        "https://tiktok.com.evil.com/video/1",
        "file:///C:/Windows/system32",
        "javascript:alert(1)",
        "ftp://youtube.com/video",
        "http://localhost/thing",
        "http://127.0.0.1/thing",
        "http://192.168.1.10/thing",
        "http://10.0.0.5/thing",
        "http://172.16.0.1/thing",
        "http://169.254.1.1/thing",
        "http://[::1]/thing",
        "http://intranet/thing",
        "http://router.local/thing",
        "https://user:pass@youtube.com/watch?v=abc",
        "https://youtube.com:8080/watch?v=abc",
        "https://youtube.com\nX-Evil: 1",
        "https://exa_mple.com/watch",
        "not-a-url",
    ],
)
def test_unsupported_or_dangerous_urls(url: str) -> None:
    assert not is_supported_url(url)


def test_platform_helpers() -> None:
    assert is_youtube_url("https://youtu.be/abc")
    assert not is_youtube_url("https://tiktok.com/@u/video/1")
    assert is_tiktok_url("https://vm.tiktok.com/abc")
    assert not is_tiktok_url("file:///tmp/x")


def test_build_audio_options(tmp_path: Path) -> None:
    options = build_options(tmp_path, DownloadMode.AUDIO, "192", playlist=True, ffmpeg="/usr/bin/ffmpeg")
    assert options["format"] == "bestaudio/best"
    assert options["noplaylist"] is False
    assert options["windowsfilenames"] is True
    assert options["ffmpeg_location"] == "/usr/bin/ffmpeg"
    assert options["postprocessors"][0] == {
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "192",
    }
    assert options["postprocessors"][1]["key"] == "FFmpegMetadata"
    assert str(options["outtmpl"]).startswith(str(tmp_path))
    assert options["outtmpl"].endswith("%(title)s.%(ext)s")


@pytest.mark.parametrize(
    ("quality", "expected"),
    [
        ("max", "bestvideo+bestaudio/best"),
        ("1080", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"),
        ("720", "bestvideo[height<=720]+bestaudio/best[height<=720]"),
    ],
)
def test_build_video_options(tmp_path: Path, quality: str, expected: str) -> None:
    options = build_options(tmp_path, DownloadMode.VIDEO, video_quality=quality)
    assert options["format"] == expected
    assert options["merge_output_format"] == "mp4"
    assert all(post["key"] != "FFmpegExtractAudio" for post in options["postprocessors"])
    assert options["postprocessors"][0]["key"] == "FFmpegMetadata"


def test_invalid_qualities_fall_back_to_defaults(tmp_path: Path) -> None:
    audio = build_options(tmp_path, "audio", "999")
    video = build_options(tmp_path, "video", video_quality="2160p")
    assert audio["postprocessors"][0]["preferredquality"] == "320"
    assert video["format"] == "bestvideo+bestaudio/best"


def test_fetch_metadata_rejects_dangerous_url_without_network() -> None:
    with pytest.raises(UnsupportedURLError):
        fetch_metadata("file:///C:/secret")


def test_download_cancelled_before_start(tmp_path: Path) -> None:
    request = DownloadRequest("https://youtu.be/abc", tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        download(request, cancel=cancel)


def test_download_rejects_unsupported_url(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedURLError):
        download(DownloadRequest("javascript:alert(1)", tmp_path))


class FakeYoutubeDL:
    """Doble de prueba que dispara el progress hook sin acceder a la red."""

    options: dict[str, Any] = {}

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        FakeYoutubeDL.options = options

    def __enter__(self) -> FakeYoutubeDL:
        return self

    def __exit__(self, *_args: object) -> Literal[False]:
        return False

    def extract_info(self, url: str, download: bool = True) -> dict[str, Any]:
        assert url == "https://youtu.be/abc"
        assert download is True
        hook = self.options["progress_hooks"][0]
        hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "speed": 1024})
        hook({"status": "finished", "info_dict": {"title": "Título de prueba"}})
        return {}


def test_download_reports_progress_title_and_conversion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    progress: list[tuple[float, str]] = []
    titles: list[str] = []
    conversions: list[bool] = []
    request = DownloadRequest("https://youtu.be/abc", tmp_path)

    download(
        request,
        on_progress=lambda fraction, speed: progress.append((fraction, speed)),
        on_title=titles.append,
        on_convert=lambda: conversions.append(True),
    )

    assert progress == [(0.5, "1.0 KB/s")]
    assert titles == ["Título de prueba"]
    assert conversions == [True]
    assert tmp_path.is_dir()


def test_find_ffmpeg_uses_imageio_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import ModuleType

    monkeypatch.setattr("shutil.which", lambda _name: None)
    fake = ModuleType("imageio_ffmpeg")
    fake.get_ffmpeg_exe = lambda: "/fake/ffmpeg"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", fake)
    assert find_ffmpeg() == "/fake/ffmpeg"
