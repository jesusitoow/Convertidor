"""Pruebas de saneamiento, detección de plataforma y organización de carpetas."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt2mp3.organizer import (
    Platform,
    artist_name,
    detect_platform,
    genre_from_text,
    genre_name,
    resolve_destination,
    sanitize_component,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('Bad Bunny: El "Mejor"', "Bad Bunny El Mejor"),
        ("Grupo/Niche*?", "Grupo Niche"),
        ("../secret", "secret"),
        ("..\\..\\Windows", "Windows"),
        ("CON", "_CON"),
        ("   ...   ", "Otros"),
        ("", "Otros"),
        ("A" * 120, "A" * 80),
    ],
)
def test_sanitize_component(raw: str, expected: str) -> None:
    assert sanitize_component(raw) == expected


def test_sanitize_custom_fallback() -> None:
    assert sanitize_component(None, fallback="Varios") == "Varios"


@pytest.mark.parametrize(
    ("text", "genre"),
    [
        ("Una salsa clásica", "Salsa"),
        ("Música vallenata", "Vallenato"),
        ("Afrobeats 2026", "Afro - Afrobeats"),
        ("Reggaeton del momento", "Urbano - Reggaeton"),
        ("K-pop coreano", "Pop"),
        ("Rock alternativo", "Rock"),
        ("EDM festival", "Electronica"),
        ("Nada reconocible", "Otros"),
    ],
)
def test_genre_from_text(text: str, genre: str) -> None:
    assert genre_from_text(text) == genre


def test_manual_genre_overrides_metadata() -> None:
    metadata = {"genre": "Rock", "title": "Canción"}
    assert genre_name(metadata, "salsa") == "Salsa"
    assert genre_name(metadata, "Mi Colección") == "Mi Colección"
    assert genre_name(metadata) == "Rock"
    assert genre_name({"title": "Canción"}) == "Otros"


def test_artist_name_prefers_artist_then_uploader() -> None:
    assert artist_name({"artist": "Bad Bunny", "uploader": "Otro"}) == "Bad Bunny"
    assert artist_name({"uploader": "Grupo Niche"}) == "Grupo Niche"
    assert artist_name({}) == "Otros"


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.youtube.com/watch?v=abc", Platform.YOUTUBE),
        ("https://youtu.be/abc", Platform.YOUTUBE),
        ("https://vm.tiktok.com/Zabc/", Platform.TIKTOK),
        ("https://www.tiktok.com/@user/video/123", Platform.TIKTOK),
        ("https://soundcloud.com/user/track", Platform.OTHER),
        ("file:///etc/passwd", Platform.OTHER),
    ],
)
def test_detect_platform(url: str, platform: Platform) -> None:
    assert detect_platform(url) is platform


def test_resolve_destination_modes(tmp_path: Path) -> None:
    base = tmp_path / "Musica"
    metadata = {"genre": "reggaeton", "uploader": "Bad Bunny"}

    assert resolve_destination(base, "artist", metadata) == base / "Bad Bunny"
    assert resolve_destination(base, "genre", metadata) == base / "Urbano - Reggaeton"
    assert resolve_destination(base, "genre_artist", metadata) == base / "Urbano - Reggaeton" / "Bad Bunny"
    assert resolve_destination(base, "flat", metadata) == base
    assert all(path.is_dir() for path in base.rglob("*") if path.is_dir()) or base.is_dir()


def test_resolve_destination_with_manual_genre_and_tiktok(tmp_path: Path) -> None:
    base = tmp_path / "Videos"
    target = resolve_destination(
        base,
        "genre_artist",
        {"uploader": "@creador"},
        manual_genre="Salsa",
        platform=Platform.TIKTOK,
    )
    assert target == base / "Salsa" / "@creador"
    assert target.is_dir()


def test_manual_genre_cannot_escape_base(tmp_path: Path) -> None:
    base = tmp_path / "Musica"
    target = resolve_destination(base, "genre", {}, manual_genre="../../../etc")
    assert target == base / "etc"
    assert base in target.parents
