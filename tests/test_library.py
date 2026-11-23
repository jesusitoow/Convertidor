"""Pruebas del escaneo recursivo y del borrado seguro de la biblioteca."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import yt2mp3.library as library
from yt2mp3.library import (
    MediaKind,
    delete_files,
    human_size,
    list_leftovers,
    list_media,
    open_path,
)


def make(folder: Path, name: str, size: int = 10, mtime: float | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_list_media_recursive_and_typed(tmp_path: Path) -> None:
    music = tmp_path / "Musica"
    videos = tmp_path / "Videos"
    make(music, " Vieja.mp3", mtime=1_000)
    make(music, "Artista/Nueva.mp3", mtime=2_000)
    make(music / "Urbano - Reggaeton" / "Bad Bunny", "Tema.mp3", mtime=3_000)
    make(videos, "Video.mp4", mtime=4_000)
    make(videos / "Creador", "Otro.mp4", mtime=5_000)
    make(music, "notas.txt")

    items = list_media(music, videos)
    assert [item.name for item in items] == ["Otro", "Video", "Tema", "Nueva", " Vieja"]
    assert items[0].kind is MediaKind.VIDEO
    assert items[0].category == "Creador"
    assert items[0].source == "Videos"
    assert items[2].category == "Urbano - Reggaeton/Bad Bunny"
    assert items[3].kind is MediaKind.AUDIO
    assert items[3].category == "Artista"


def test_list_media_missing_folders(tmp_path: Path) -> None:
    assert list_media(tmp_path / "nope", tmp_path / "nope2") == []


def test_leftovers_detected_recursively(tmp_path: Path) -> None:
    make(tmp_path, "a.mp3")
    part = make(tmp_path, "b.webm.part")
    nested = make(tmp_path / "Artista", "c.mp4.ytdl")
    temp = make(tmp_path / "Artista", "d.temp")
    assert list_leftovers(tmp_path) == [temp, nested, part] or set(list_leftovers(tmp_path)) == {
        part,
        nested,
        temp,
    }


def test_delete_files_removes_nested_and_counts(tmp_path: Path) -> None:
    music = tmp_path / "Musica"
    videos = tmp_path / "Videos"
    a = make(music / "Bad Bunny", "a.mp3")
    b = make(videos / "Creador", "b.mp4")
    deleted, errors = delete_files([a, b], [music, videos], use_trash=False)
    assert (deleted, errors) == (2, [])
    assert not a.exists() and not b.exists()


def test_delete_refuses_files_outside_allowed_roots(tmp_path: Path) -> None:
    music = tmp_path / "music"
    music.mkdir()
    outside = make(tmp_path, "secret.mp3")
    deleted, errors = delete_files([outside], [music], use_trash=False)
    assert deleted == 0 and len(errors) == 1
    assert outside.exists()


def test_delete_refuses_other_file_types_and_symlinks(tmp_path: Path) -> None:
    doc = make(tmp_path, "tesis.docx")
    symbol = tmp_path / "link.mp3"
    try:
        symbol.symlink_to(doc)
    except OSError:  # Windows puede requerir permisos elevados
        symbol.unlink(missing_ok=True)
    deleted, errors = delete_files([doc, symbol], [tmp_path], use_trash=False)
    assert deleted == 0
    assert len(errors) == 2
    assert doc.exists()


def test_delete_to_trash_requires_send2trash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = make(tmp_path, "a.mp3")
    monkeypatch.setattr(library, "_send2trash", None)
    deleted, errors = delete_files([target], [tmp_path], use_trash=True)
    assert deleted == 0 and "papelera" in errors[0]
    assert target.exists()


def test_human_size() -> None:
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(5 * 1024 * 1024) == "5.0 MB"
    assert human_size(-10) == "0 B"


def test_open_path_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_path(tmp_path / "no-existe.mp3")
