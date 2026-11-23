"""Pruebas de configuración persistente y tolerante a fallos."""

from __future__ import annotations

import json
from pathlib import Path

from yt2mp3.config import Settings
from yt2mp3.organizer import OrganizeMode, VideoQuality


def test_default_folders_are_universal() -> None:
    settings = Settings()
    assert Path(settings.music_folder).parts[-2:] == ("Downloads", "Musica")
    assert Path(settings.video_folder).parts[-2:] == ("Downloads", "Videos")
    assert settings.audio_quality == "320"
    assert settings.video_quality == VideoQuality.MAX.value
    assert settings.organize_mode == OrganizeMode.ARTIST.value
    assert settings.appearance == "dark"


def test_roundtrip(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    original = Settings(
        music_folder=str(tmp_path / "m"),
        video_folder=str(tmp_path / "v"),
        audio_quality="192",
        video_quality="720",
        organize_mode="genre_artist",
        appearance="light",
        auto_download=False,
        playlist=True,
        legal_accepted=True,
    )
    original.save(config)
    loaded = Settings.load(config)
    assert loaded == original
    assert json.loads(config.read_text(encoding="utf-8"))["audio_quality"] == "192"


def test_missing_and_corrupt_file_give_defaults(tmp_path: Path) -> None:
    assert Settings.load(tmp_path / "nada.json") == Settings()
    config = tmp_path / "config.json"
    config.write_text("{ esto no es json", encoding="utf-8")
    assert Settings.load(config) == Settings()
    config.write_text('["no", "es", "un", "dict"]', encoding="utf-8")
    assert Settings.load(config) == Settings()


def test_invalid_values_are_sanitized(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "audio_quality": "999",
                "video_quality": "2160",
                "organize_mode": "aleatorio",
                "appearance": "neon",
                "auto_download": "si",
                "playlist": 1,
                "music_folder": "",
            }
        ),
        encoding="utf-8",
    )
    settings = Settings.load(config)
    assert settings.audio_quality == "320"
    assert settings.video_quality == "max"
    assert settings.organize_mode == "artist"
    assert settings.appearance == "dark"
    assert settings.auto_download is True
    assert settings.playlist is False
    assert settings.music_folder


def test_legacy_keys_are_migrated(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"folder": "/tmp/antigua", "quality": "128"}', encoding="utf-8")
    settings = Settings.load(config)
    assert settings.music_folder == "/tmp/antigua"
    assert settings.audio_quality == "128"


def test_ensure_folders_creates_both_roots(tmp_path: Path) -> None:
    music, video = tmp_path / "m" / "Musica", tmp_path / "v" / "Videos"
    settings = Settings(music_folder=str(music), video_folder=str(video))
    created = settings.ensure_folders()
    assert created == (music, video)
    assert music.is_dir() and video.is_dir()


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    settings = Settings(music_folder=str(tmp_path / "m"))
    settings.save(tmp_path / "no-existe" / "config.json")  # crea el directorio, no debe lanzar
    assert (tmp_path / "no-existe" / "config.json").is_file()
