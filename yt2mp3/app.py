"""Interfaz gráfica de YT2MP3 (único módulo que importa CustomTkinter)."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

from . import __version__
from .config import APPEARANCES, AUDIO_QUALITIES, Settings
from .downloader import (
    DownloadCancelled,
    DownloadRequest,
    UnsupportedURLError,
    download,
    fetch_metadata,
    find_ffmpeg,
    is_supported_url,
)
from .library import (
    MediaFile,
    MediaKind,
    delete_files,
    human_size,
    list_leftovers,
    list_media,
    open_containing_folder,
    open_path,
    trash_available,
)
from .organizer import (
    DOWNLOAD_LABELS,
    ORGANIZE_LABELS,
    VIDEO_QUALITY_LABELS,
    DownloadMode,
    OrganizeMode,
    VideoQuality,
    resolve_destination,
)

# --------------------------------------------------------------------------- tema
Color = str | tuple[str, str]  # (modo claro, modo oscuro)
BG: Color = ("#f4f4fa", "#0b0b12")
SURFACE: Color = ("#ffffff", "#14141f")
FIELD: Color = ("#eceef6", "#1c1c2b")
FIELD_HOVER: Color = ("#dfe2f0", "#272740")
TEXT: Color = ("#16161d", "#f4f4f9")
MUTED: Color = ("#6b6b85", "#8e8ea8")
ACCENT: Color = "#7c5cff"
ACCENT_HOVER = "#6a49f0"
OK = "#22c55e"
ERR = "#ef4444"
DANGER = "#dc2626"
DANGER_HOVER = "#b91c1c"

FONT = "Segoe UI"
STATES: dict[str, tuple[str, Color]] = {
    "queued": ("En cola", MUTED),
    "preparing": ("Preparando", ACCENT),
    "downloading": ("Descargando", ACCENT),
    "converting": ("Convirtiendo", ACCENT),
    "done": ("Completado", OK),
    "error": ("Error", ERR),
    "cancelled": ("Cancelado", MUTED),
}
FINAL_STATES = frozenset({"done", "error", "cancelled"})
WORKERS = 2

_MODE_BY_LABEL = {label: mode for mode, label in DOWNLOAD_LABELS.items()}
_ORG_BY_LABEL = {label: mode for mode, label in ORGANIZE_LABELS.items()}
_VIDEO_BY_LABEL = {label: quality for quality, label in VIDEO_QUALITY_LABELS.items()}
_APPEARANCE_LABELS = {"Oscuro": "dark", "Claro": "light", "Sistema": "system"}
_APPEARANCE_BY_VALUE = {value: label for label, value in _APPEARANCE_LABELS.items()}


def font(size: int = 13, weight: str = "normal") -> Any:
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def short(text: str, limit: int = 52) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def ghost_button(master: Any, text: str, command: Callable[[], None], width: int = 0, height: int = 36) -> Any:
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=10,
        fg_color=FIELD,
        hover_color=FIELD_HOVER,
        text_color=TEXT,
        font=font(12, "bold"),
    )


def accent_button(master: Any, text: str, command: Callable[[], None], width: int = 0, height: int = 36) -> Any:
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=10,
        fg_color=ACCENT,
        hover_color=ACCENT_HOVER,
        text_color="white",
        font=font(12, "bold"),
    )


def danger_button(master: Any, text: str, command: Callable[[], None], width: int = 0, height: int = 36) -> Any:
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=10,
        fg_color=DANGER,
        hover_color=DANGER_HOVER,
        text_color="white",
        font=font(12, "bold"),
    )


# ------------------------------------------------------------------------- cola UI


class JobRow(ctk.CTkFrame):
    """Fila de la cola: título, estado, progreso, velocidad y botón cancelar/quitar."""

    def __init__(self, master: Any, label: str, on_close: Callable[[], None]) -> None:
        super().__init__(master, fg_color=FIELD, corner_radius=14)
        self.alive = True
        self.state_key = "queued"
        self.columnconfigure(0, weight=1)

        self.title_lbl = ctk.CTkLabel(self, text=short(label), anchor="w", text_color=TEXT, font=font(13, "bold"))
        self.title_lbl.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=(12, 0))
        self.state_lbl = ctk.CTkLabel(self, text=STATES["queued"][0], text_color=MUTED, font=font(11, "bold"))
        self.state_lbl.grid(row=0, column=1, padx=(0, 8), pady=(12, 0))
        self.close_btn = ctk.CTkButton(
            self,
            text="✕",
            width=28,
            height=28,
            corner_radius=8,
            fg_color="transparent",
            hover_color=FIELD_HOVER,
            text_color=MUTED,
            font=font(12, "bold"),
            command=on_close,
        )
        self.close_btn.grid(row=0, column=2, padx=(0, 10), pady=(10, 0))

        self.bar = ctk.CTkProgressBar(self, height=6, corner_radius=3, fg_color=SURFACE, progress_color=ACCENT)
        self.bar.set(0)
        self.bar.grid(row=1, column=0, columnspan=3, sticky="ew", padx=16, pady=(8, 4))
        self.detail_lbl = ctk.CTkLabel(self, text="", anchor="e", text_color=MUTED, font=font(10))
        self.detail_lbl.grid(row=2, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 10))

    @property
    def finished(self) -> bool:
        return self.state_key in FINAL_STATES

    def set_title(self, text: str) -> None:
        if self.alive:
            self.title_lbl.configure(text=short(text))

    def set_progress(self, fraction: float, detail: str = "") -> None:
        if not self.alive:
            return
        self.bar.set(max(0.0, min(1.0, fraction)))
        self.detail_lbl.configure(text=f"{fraction * 100:.0f}% · {detail}" if detail else f"{fraction * 100:.0f}%")

    def set_state(self, key: str) -> None:
        if not self.alive:
            return
        self.state_key = key
        text, color = STATES.get(key, STATES["queued"])
        self.state_lbl.configure(text=text, text_color=color)
        if key == "done":
            self.bar.set(1)
            self.bar.configure(progress_color=OK)
        elif key == "error":
            self.bar.configure(progress_color=ERR)
        elif key == "converting":
            self.bar.set(1)

    def destroy(self) -> None:
        self.alive = False
        super().destroy()


@dataclass
class Job:
    """Trabajo pendiente: petición de descarga + fila + señal de cancelación."""

    request: DownloadRequest
    base: Path
    organize_mode: str
    manual_genre: str
    row: JobRow
    cancel: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True, slots=True)
class UIEvent:
    """Mensaje thread-safe enviado por los workers a la interfaz."""

    kind: str
    job: Job
    value: Any = None
    detail: str = ""


# ------------------------------------------------------------------------- aplicación


class App(ctk.CTk):
    """Ventana principal con pestañas Descargar / Biblioteca / Ajustes."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        ctk.set_appearance_mode(self.settings.appearance)
        ctk.set_default_color_theme("blue")

        self.title(f"YT2MP3 · MediaVault v{__version__}")
        self.geometry("860x780")
        self.minsize(720, 640)
        self.configure(fg_color=BG)

        self.ffmpeg = find_ffmpeg()
        self.jobs_q: queue.Queue[Job] = queue.Queue()
        self.ui_q: queue.Queue[UIEvent] = queue.Queue()
        self.jobs: list[Job] = []
        self.lib_vars: list[tuple[Any, MediaFile]] = []
        self._syncing = False

        self._build_header()
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=26, pady=(10, 18))
        self.tabs = ctk.CTkTabview(self.body, fg_color=SURFACE, corner_radius=20, segmented_button_fg_color=FIELD)
        self.tabs.pack(fill="both", expand=True)
        for name in ("Descargar", "Biblioteca", "Ajustes"):
            self.tabs.add(name)
        self.download_view = self.tabs.tab("Descargar")
        self.library_view = self.tabs.tab("Biblioteca")
        self.settings_view = self.tabs.tab("Ajustes")
        self._build_download_view()
        self._build_library_view()
        self._build_settings_view()
        self.tabs.set("Descargar")
        self.mode_seg.set(DOWNLOAD_LABELS[DownloadMode.AUDIO])
        self._show_quality_panel(DownloadMode.AUDIO)
        self._sync_controls()

        try:
            self.settings.ensure_folders()
        except OSError as exc:
            self._status(f"No se pudieron crear las carpetas: {exc}", ERR)
        if not self.ffmpeg:
            self._status("No se encontró ffmpeg. Reinstala las dependencias (install.bat).", ERR)

        for _ in range(WORKERS):
            threading.Thread(target=self._worker, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)

    # --------------------------------------------------------------- construcción
    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=28, pady=(20, 0))
        ctk.CTkLabel(bar, text="♫", text_color=ACCENT, font=font(30, "bold")).pack(side="left")
        ctk.CTkLabel(bar, text=" YT2MP3", text_color=TEXT, font=font(24, "bold")).pack(side="left")
        ctk.CTkLabel(
            bar,
            text=f"  MediaVault v{__version__}  ·  YouTube · TikTok · y más",
            text_color=MUTED,
            font=font(11),
        ).pack(side="left", pady=(8, 0))

    def _build_download_view(self) -> None:
        view = self.download_view
        card = ctk.CTkFrame(view, fg_color=SURFACE, corner_radius=20)
        card.pack(fill="x", padx=18, pady=(18, 0))
        ctk.CTkLabel(card, text="Pega uno o varios enlaces", text_color=TEXT, font=font(16, "bold")).pack(
            anchor="w", padx=20, pady=(18, 0)
        )
        ctk.CTkLabel(
            card,
            text="YouTube, TikTok e plataformas públicas soportadas. Un link por línea.",
            text_color=MUTED,
            font=font(12),
        ).pack(anchor="w", padx=20, pady=(0, 10))

        self.links_box = ctk.CTkTextbox(
            card, height=86, corner_radius=14, fg_color=FIELD, text_color=TEXT, font=font(12)
        )
        self.links_box.pack(fill="x", padx=20)
        self.links_box.bind("<<Paste>>", lambda _event: self.after(120, self._submit_if_auto))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(10, 0))
        self.auto_sw = ctk.CTkSwitch(
            actions,
            text="Descargar al pegar",
            progress_color=ACCENT,
            text_color=MUTED,
            font=font(12),
            command=self._change_auto,
        )
        self.auto_sw.pack(side="left")
        self.playlist_sw = ctk.CTkSwitch(
            actions,
            text="Playlist completa",
            progress_color=ACCENT,
            text_color=MUTED,
            font=font(12),
            command=self._change_playlist,
        )
        self.playlist_sw.pack(side="left", padx=(18, 0))
        ghost_button(actions, "Pegar", self.paste_clipboard, width=74, height=38).pack(side="left", padx=(18, 0))
        accent_button(actions, "Descargar", self.submit, width=124, height=38).pack(side="right")

        selector = ctk.CTkFrame(card, fg_color="transparent")
        selector.pack(fill="x", padx=20, pady=(14, 0))
        ctk.CTkLabel(selector, text="Tipo", text_color=MUTED, font=font(11, "bold")).pack(anchor="w")
        self.mode_seg = ctk.CTkSegmentedButton(
            selector,
            values=list(DOWNLOAD_LABELS.values()),
            height=32,
            corner_radius=10,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            fg_color=FIELD,
            unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER,
            text_color=TEXT,
            font=font(11, "bold"),
            command=self._change_type,
        )
        self.mode_seg.pack(fill="x", pady=(4, 0))

        quality_row = ctk.CTkFrame(card, fg_color="transparent")
        quality_row.pack(fill="x", pady=(10, 0))
        self.audio_quality_frame = ctk.CTkFrame(quality_row, fg_color="transparent")
        self.video_quality_frame = ctk.CTkFrame(quality_row, fg_color="transparent")
        ctk.CTkLabel(self.audio_quality_frame, text="Audio (kbps)", text_color=MUTED, font=font(11, "bold")).pack(
            anchor="w"
        )
        self.dl_audio_seg = ctk.CTkSegmentedButton(
            self.audio_quality_frame,
            values=list(AUDIO_QUALITIES),
            height=30,
            corner_radius=10,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            fg_color=FIELD,
            unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER,
            text_color=TEXT,
            font=font(11),
            command=self._change_audio_quality,
        )
        self.dl_audio_seg.pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(self.video_quality_frame, text="Calidad de vídeo", text_color=MUTED, font=font(11, "bold")).pack(
            anchor="w"
        )
        self.dl_video_seg = ctk.CTkSegmentedButton(
            self.video_quality_frame,
            values=list(VIDEO_QUALITY_LABELS.values()),
            height=30,
            corner_radius=10,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            fg_color=FIELD,
            unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER,
            text_color=TEXT,
            font=font(11),
            command=self._change_video_quality,
        )
        self.dl_video_seg.pack(anchor="w", pady=(4, 0))

        organization = ctk.CTkFrame(card, fg_color="transparent")
        organization.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(organization, text="Organización", text_color=MUTED, font=font(11, "bold")).pack(anchor="w")
        self.dl_org_seg = ctk.CTkSegmentedButton(
            organization,
            values=list(ORGANIZE_LABELS.values()),
            height=30,
            corner_radius=10,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            fg_color=FIELD,
            unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER,
            text_color=TEXT,
            font=font(11),
            command=self._change_organization,
        )
        self.dl_org_seg.pack(fill="x", pady=(4, 0))
        self.manual_entry = ctk.CTkEntry(
            card,
            height=34,
            corner_radius=10,
            border_width=0,
            fg_color=FIELD,
            text_color=TEXT,
            placeholder_text="Género / carpeta manual (opcional, p. ej. Salsa)",
            placeholder_text_color=MUTED,
            font=font(11),
        )
        self.manual_entry.pack(fill="x", padx=20, pady=(8, 0))

        self.status_lbl = ctk.CTkLabel(card, text="Listo.", anchor="w", text_color=MUTED, font=font(12))
        self.status_lbl.pack(fill="x", padx=20, pady=(10, 14))

        head = ctk.CTkFrame(view, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(18, 8))
        ctk.CTkLabel(head, text="Cola de descargas", text_color=TEXT, font=font(15, "bold")).pack(side="left")
        ghost_button(head, "Limpiar lista", self.clear_finished, height=30).pack(side="right")

        self.queue_box = ctk.CTkScrollableFrame(view, fg_color=SURFACE, corner_radius=20)
        self.queue_box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.queue_empty = ctk.CTkLabel(
            self.queue_box,
            text="Todavía no hay descargas.\nPega un link para empezar.",
            text_color=MUTED,
            font=font(12),
            justify="center",
        )
        self.queue_empty.pack(pady=50)

    def _build_library_view(self) -> None:
        view = self.library_view
        head = ctk.CTkFrame(view, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(18, 8))
        ctk.CTkLabel(head, text="Biblioteca", text_color=TEXT, font=font(15, "bold")).pack(side="left")
        self.lib_stats = ctk.CTkLabel(head, text="", text_color=MUTED, font=font(11))
        self.lib_stats.pack(side="left", padx=12)
        ghost_button(head, "Actualizar", self._refresh_library, height=30).pack(side="right")
        ghost_button(head, "Abrir carpetas", self.open_folders, height=30).pack(side="right", padx=(0, 8))

        self.lib_box = ctk.CTkScrollableFrame(view, fg_color=SURFACE, corner_radius=20)
        self.lib_box.pack(fill="both", expand=True, padx=18)

        self.lib_msg = ctk.CTkLabel(view, text="", anchor="w", text_color=MUTED, font=font(11))
        self.lib_msg.pack(fill="x", padx=18, pady=(8, 0))

        actions = ctk.CTkFrame(view, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(8, 18))
        ghost_button(actions, "Seleccionar todo", self._toggle_all).pack(side="left")
        danger_button(actions, "Eliminar seleccionados", self._delete_selected).pack(side="left", padx=(8, 0))
        ghost_button(actions, "Limpiar temporales", self._clean_leftovers).pack(side="right")

    def _build_settings_view(self) -> None:
        view = self.settings_view
        card = ctk.CTkFrame(view, fg_color=SURFACE, corner_radius=20)
        card.pack(fill="x", padx=18, pady=18)

        def block(title: str, subtitle: str) -> Any:
            wrap = ctk.CTkFrame(card, fg_color="transparent")
            wrap.pack(fill="x", padx=20, pady=(16, 0))
            ctk.CTkLabel(wrap, text=title, text_color=TEXT, font=font(14, "bold")).pack(anchor="w")
            ctk.CTkLabel(wrap, text=subtitle, text_color=MUTED, font=font(11)).pack(anchor="w", pady=(0, 8))
            return wrap

        def folder_block(title: str, subtitle: str, key: str) -> Any:
            wrap = block(title, subtitle)
            line = ctk.CTkFrame(wrap, fg_color="transparent")
            line.pack(fill="x")
            entry = ctk.CTkEntry(
                line, height=38, corner_radius=10, border_width=0, fg_color=FIELD, text_color=TEXT, font=font(11)
            )
            entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
            entry.bind("<FocusOut>", lambda _event, k=key, e=entry: self._apply_folder(k, e.get()))
            ghost_button(line, "Cambiar…", partial(self._choose_folder, key), width=96, height=38).pack(side="left")
            return entry

        self.set_music_entry = folder_block("Carpeta de música", "MP3 y sus subcarpetas de artista/género.", "music")
        self.set_video_entry = folder_block("Carpeta de vídeos", "MP4 de YouTube, TikTok y otras plataformas.", "video")

        defaults = block("Valores por defecto", "Se aplican a las nuevas descargas.")
        ctk.CTkLabel(defaults, text="Calidad de audio", text_color=MUTED, font=font(11, "bold")).pack(anchor="w")
        self.set_audio_seg = ctk.CTkSegmentedButton(
            defaults,
            values=list(AUDIO_QUALITIES),
            height=30,
            corner_radius=10,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            fg_color=FIELD,
            unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER,
            text_color=TEXT,
            font=font(11),
            command=self._change_audio_quality,
        )
        self.set_audio_seg.pack(anchor="w", pady=(4, 10))
        ctk.CTkLabel(defaults, text="Calidad de vídeo", text_color=MUTED, font=font(11, "bold")).pack(anchor="w")
        self.set_video_seg = ctk.CTkSegmentedButton(
            defaults,
            values=list(VIDEO_QUALITY_LABELS.values()),
            height=30,
            corner_radius=10,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            fg_color=FIELD,
            unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER,
            text_color=TEXT,
            font=font(11),
            command=self._change_video_quality,
        )
        self.set_video_seg.pack(anchor="w", pady=(4, 10))
        ctk.CTkLabel(defaults, text="Organización", text_color=MUTED, font=font(11, "bold")).pack(anchor="w")
        self.set_org_seg = ctk.CTkSegmentedButton(
            defaults,
            values=list(ORGANIZE_LABELS.values()),
            height=30,
            corner_radius=10,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            fg_color=FIELD,
            unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER,
            text_color=TEXT,
            font=font(11),
            command=self._change_organization,
        )
        self.set_org_seg.pack(fill="x", pady=(4, 0))

        look = block("Apariencia", "Oscuro, claro o el tema del sistema.")
        self.set_appearance_seg = ctk.CTkSegmentedButton(
            look,
            values=list(_APPEARANCE_LABELS),
            height=32,
            corner_radius=10,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            fg_color=FIELD,
            unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER,
            text_color=TEXT,
            font=font(11),
            command=self._change_appearance,
        )
        self.set_appearance_seg.pack(anchor="w")

        legal = block("Aviso legal", "Descarga solo contenido propio, licenciado o con permiso.")
        self.legal_var = ctk.BooleanVar(value=self.settings.legal_accepted)
        ctk.CTkCheckBox(
            legal,
            text="He leído y acepto el aviso legal",
            variable=self.legal_var,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=TEXT,
            font=font(11),
            command=self._change_legal,
        ).pack(anchor="w", pady=(0, 6))
        ctk.CTkLabel(
            legal,
            text="Esta herramienta es para usarla con contenido tuyo, de dominio público o con autorización.\n"
            "Descargar material con derechos de autor puede infringir los términos del servicio y la ley.",
            text_color=MUTED,
            font=font(10),
            justify="left",
        ).pack(anchor="w", pady=(0, 16))
        ctk.CTkLabel(
            card,
            text=f"YT2MP3 v{__version__} · yt-dlp + FFmpeg · MIT © 2026 Jesús Franco",
            text_color=MUTED,
            font=font(10),
        ).pack(anchor="w", padx=20, pady=(4, 18))

    # --------------------------------------------------------------- sincronización
    def _sync_controls(self) -> None:
        """Refleja ``settings`` en ambos paneles sin disparar sus callbacks."""

        self._syncing = True
        try:
            self.auto_sw.select() if self.settings.auto_download else self.auto_sw.deselect()
            self.playlist_sw.select() if self.settings.playlist else self.playlist_sw.deselect()
            self.legal_var.set(self.settings.legal_accepted)

            self.dl_audio_seg.set(self.settings.audio_quality)
            self.set_audio_seg.set(self.settings.audio_quality)
            quality = VideoQuality(self.settings.video_quality)
            self.dl_video_seg.set(VIDEO_QUALITY_LABELS[quality])
            self.set_video_seg.set(VIDEO_QUALITY_LABELS[quality])
            organization = OrganizeMode(self.settings.organize_mode)
            self.dl_org_seg.set(ORGANIZE_LABELS[organization])
            self.set_org_seg.set(ORGANIZE_LABELS[organization])
            self.set_appearance_seg.set(_APPEARANCE_BY_VALUE.get(self.settings.appearance, "Oscuro"))
            self.set_music_entry.delete(0, "end")
            self.set_music_entry.insert(0, self.settings.music_folder)
            self.set_video_entry.delete(0, "end")
            self.set_video_entry.insert(0, self.settings.video_folder)
        finally:
            self._syncing = False

    def _persist(self) -> None:
        self.settings.save()

    def _show_quality_panel(self, mode: DownloadMode) -> None:
        if mode is DownloadMode.AUDIO:
            self.video_quality_frame.pack_forget()
            self.audio_quality_frame.pack(fill="x")
        else:
            self.audio_quality_frame.pack_forget()
            self.video_quality_frame.pack(fill="x")

    # -------------------------------------------------------------- change handlers
    def _change_auto(self) -> None:
        self.settings.auto_download = bool(self.auto_sw.get())
        self._persist()

    def _change_playlist(self) -> None:
        self.settings.playlist = bool(self.playlist_sw.get())
        self._persist()

    def _change_legal(self) -> None:
        self.settings.legal_accepted = bool(self.legal_var.get())
        self._persist()

    def _change_type(self, label: str) -> None:
        if self._syncing:
            return
        mode = _MODE_BY_LABEL.get(label, DownloadMode.AUDIO)
        self._show_quality_panel(mode)

    def _change_audio_quality(self, value: str) -> None:
        if self._syncing:
            return
        self.settings.audio_quality = value
        self._sync_controls()
        self._persist()

    def _change_video_quality(self, label: str) -> None:
        if self._syncing:
            return
        quality = _VIDEO_BY_LABEL.get(label, VideoQuality.MAX)
        self.settings.video_quality = quality.value
        self._sync_controls()
        self._persist()

    def _change_organization(self, label: str) -> None:
        if self._syncing:
            return
        self.settings.organize_mode = _ORG_BY_LABEL.get(label, OrganizeMode.ARTIST).value
        self._sync_controls()
        self._persist()

    def _change_appearance(self, label: str) -> None:
        if self._syncing:
            return
        mode = _APPEARANCE_LABELS.get(label, "dark")
        if mode in APPEARANCES:
            self.settings.appearance = mode
            ctk.set_appearance_mode(mode)
            self._persist()

    # --------------------------------------------------------------------- descarga
    def _status(self, text: str, color: Color = MUTED) -> None:
        self.status_lbl.configure(text=text, text_color=color)

    def paste_clipboard(self) -> None:
        try:
            text = str(self.clipboard_get()).strip()
        except Exception:  # noqa: BLE001 - portapapeles vacío o sin texto
            return
        if not text:
            return
        current = self.links_box.get("1.0", "end").strip()
        self.links_box.delete("1.0", "end")
        self.links_box.insert("1.0", f"{current}\n{text}".strip() if current else text)
        self._submit_if_auto()

    def _submit_if_auto(self) -> None:
        if self.settings.auto_download and self.links_box.get("1.0", "end").strip():
            self.submit()

    def submit(self) -> None:
        text = self.links_box.get("1.0", "end").strip()
        if not text:
            self._status("Pega al menos un enlace.", ERR)
            return
        if not self.ffmpeg:
            self._status("No se encontró ffmpeg. Reinstala las dependencias (install.bat).", ERR)
            return

        links = [line.strip() for line in text.splitlines() if line.strip()]
        valid = [link for link in links if is_supported_url(link)]
        rejected = len(links) - len(valid)
        if not valid:
            self._status("Ningún enlace es válido o está en una plataforma permitida.", ERR)
            return

        mode = _MODE_BY_LABEL.get(str(self.mode_seg.get()), DownloadMode.AUDIO)
        base = self.settings.music_path if mode is DownloadMode.AUDIO else self.settings.video_path
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._status(f"No se pudo crear {base}: {exc}", ERR)
            return

        self.queue_empty.pack_forget()
        for link in valid:
            request = DownloadRequest(
                url=link,
                destination=base,
                mode=mode,
                audio_quality=self.settings.audio_quality,
                video_quality=self.settings.video_quality,
                playlist=bool(self.playlist_sw.get()),
            )
            row = JobRow(self.queue_box, link, on_close=lambda: None)
            job = Job(
                request=request,
                base=base,
                organize_mode=self.settings.organize_mode,
                manual_genre=self.manual_entry.get().strip(),
                row=row,
            )
            row.close_btn.configure(command=lambda j=job: self._close_job(j))
            row.pack(fill="x", padx=8, pady=5)
            self.jobs.append(job)
            self.jobs_q.put(job)

        self.links_box.delete("1.0", "end")
        suffix = f" · {rejected} descartado(s)" if rejected else ""
        self._status(f"{len(valid)} descarga(s) en cola{suffix}")
        self._update_summary()

    def _close_job(self, job: Job) -> None:
        """✕ cancela si está en curso; si ya terminó, quita la fila."""

        if job.row.finished:
            self._remove_job(job)
        else:
            job.cancel.set()
            job.row.set_state("cancelled")
        self._update_summary()

    def _remove_job(self, job: Job) -> None:
        if job in self.jobs:
            self.jobs.remove(job)
        job.row.destroy()
        if not self.jobs:
            self.queue_empty.pack(pady=50)

    def clear_finished(self) -> None:
        """Quita de la pantalla las filas terminadas, canceladas o con error."""

        for job in [item for item in self.jobs if item.row.finished]:
            self._remove_job(job)
        self._status("Lista limpiada (los archivos siguen en disco).")
        self._update_summary()

    def _update_summary(self) -> None:
        running = sum(1 for job in self.jobs if job.row.state_key in {"downloading", "converting", "preparing"})
        waiting = sum(1 for job in self.jobs if job.row.state_key == "queued")
        if running or waiting:
            self._status(f"Descargando {running} · en cola {waiting}")
        elif self.jobs:
            errors = sum(1 for job in self.jobs if job.row.state_key == "error")
            done = sum(1 for job in self.jobs if job.row.state_key == "done")
            if errors:
                self._status(f"{done} completadas, {errors} con error.", ERR)
            elif done:
                self._status(f"Todo listo ✔ ({done} descargadas)", OK)
            else:
                self._status("Listo.")
        else:
            self._status("Listo.")

    # ---------------------------------------------------------------------- workers
    def _worker(self) -> None:
        while True:
            job = self.jobs_q.get()
            try:
                if job.cancel.is_set():
                    raise DownloadCancelled()
                self.ui_q.put(UIEvent("title", job, "Obteniendo metadatos…"))
                self.ui_q.put(UIEvent("state", job, "preparing"))
                metadata = fetch_metadata(job.request.url, self.ffmpeg, job.request.playlist)
                if job.cancel.is_set():
                    raise DownloadCancelled()

                platform = job.request.platform
                destination = resolve_destination(job.base, job.organize_mode, metadata, job.manual_genre, platform)
                request = replace(job.request, destination=destination)
                self.ui_q.put(UIEvent("state", job, "downloading"))

                def on_progress(value: float, detail: str, j: Job = job) -> None:
                    self.ui_q.put(UIEvent("progress", j, value, detail))

                def on_title(title: str, j: Job = job) -> None:
                    self.ui_q.put(UIEvent("title", j, title))

                def on_convert(j: Job = job) -> None:
                    self.ui_q.put(UIEvent("state", j, "converting"))

                download(
                    request,
                    ffmpeg=self.ffmpeg,
                    on_progress=on_progress,
                    on_title=on_title,
                    on_convert=on_convert,
                    cancel=job.cancel,
                )
                self.ui_q.put(UIEvent("state", job, "done"))
            except DownloadCancelled:
                self.ui_q.put(UIEvent("state", job, "cancelled"))
            except UnsupportedURLError as exc:
                self.ui_q.put(UIEvent("error", job, detail=f"URL no permitida: {exc}"))
            except Exception as exc:  # noqa: BLE001 - se reporta en la fila
                if job.cancel.is_set():
                    self.ui_q.put(UIEvent("state", job, "cancelled"))
                else:
                    message = (str(exc).splitlines() or ["Error desconocido"])[0].replace("ERROR: ", "")
                    self.ui_q.put(UIEvent("error", job, detail=message[:200]))
            finally:
                self.jobs_q.task_done()

    def _poll(self) -> None:
        """Aplica eventos de los workers siempre en el hilo de la interfaz."""

        try:
            while True:
                event = self.ui_q.get_nowait()
                row = event.job.row
                if event.kind == "state":
                    row.set_state(str(event.value))
                    self._update_summary()
                elif event.kind == "progress":
                    row.set_progress(float(event.value), event.detail)
                elif event.kind == "title":
                    row.set_title(str(event.value))
                elif event.kind == "error":
                    row.set_state("error")
                    self._update_summary()
                    self._status(event.detail or "Error en la descarga.", ERR)
                self.ui_q.task_done()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # --------------------------------------------------------------- biblioteca
    def _refresh_library(self) -> None:
        for widget in self.lib_box.winfo_children():
            widget.destroy()
        self.lib_vars.clear()
        try:
            media = list_media(*self.settings.folders)
        except OSError as exc:
            self._lib_message(f"No se pudo leer la biblioteca: {exc}", ERR)
            return

        total = sum(item.size for item in media)
        audios = sum(1 for item in media if item.kind is MediaKind.AUDIO)
        self.lib_stats.configure(text=f"{len(media)} archivos · {audios} MP3 · {human_size(total)}" if media else "")
        self.lib_msg.configure(text=f"Música: {self.settings.music_path}   ·   Vídeos: {self.settings.video_path}")
        if not media:
            ctk.CTkLabel(
                self.lib_box,
                text="Todavía no hay archivos. Descarga algo o cambia las carpetas en Ajustes.",
                text_color=MUTED,
                font=font(12),
            ).pack(pady=50)
            return

        for item in media:
            var = ctk.BooleanVar(value=False)
            self.lib_vars.append((var, item))
            row = ctk.CTkFrame(self.lib_box, fg_color=FIELD, corner_radius=12)
            row.pack(fill="x", padx=8, pady=4)
            ctk.CTkCheckBox(
                row,
                text="",
                variable=var,
                width=24,
                checkbox_width=20,
                checkbox_height=20,
                corner_radius=6,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                border_color=MUTED,
            ).pack(side="left", padx=(14, 4), pady=10)
            ctk.CTkLabel(row, text=short(item.name, 44), anchor="w", text_color=TEXT, font=font(12)).pack(
                side="left", fill="x", expand=True, padx=(4, 8)
            )
            ctk.CTkLabel(row, text=f"{item.kind.value} · {item.category}", text_color=MUTED, font=font(10)).pack(
                side="left", padx=(0, 8)
            )
            ctk.CTkLabel(row, text=human_size(item.size), text_color=MUTED, font=font(10)).pack(
                side="left", padx=(0, 8)
            )
            ctk.CTkButton(
                row,
                text="📂",
                width=30,
                height=28,
                corner_radius=8,
                fg_color="transparent",
                hover_color=FIELD_HOVER,
                text_color=MUTED,
                font=font(12),
                command=lambda path=item.path: self._safe_open(open_containing_folder, path),
            ).pack(side="right", padx=(0, 2))
            ctk.CTkButton(
                row,
                text="▶",
                width=30,
                height=28,
                corner_radius=8,
                fg_color="transparent",
                hover_color=FIELD_HOVER,
                text_color=ACCENT,
                font=font(12, "bold"),
                command=lambda path=item.path: self._safe_open(open_path, path),
            ).pack(side="right", padx=(0, 8))

    def _safe_open(self, opener: Callable[[Path], None], path: Path) -> None:
        try:
            opener(path)
        except Exception as exc:  # noqa: BLE001 - el sistema puede no tener app asociada
            self._lib_message(f"No se pudo abrir: {exc}", ERR)

    def _lib_message(self, text: str, color: Color = MUTED) -> None:
        self.lib_msg.configure(text=text, text_color=color)

    def _toggle_all(self) -> None:
        target = not all(var.get() for var, _ in self.lib_vars) if self.lib_vars else False
        for var, _ in self.lib_vars:
            var.set(target)

    def _delete_selected(self) -> None:
        picked = [item for var, item in self.lib_vars if var.get()]
        if not picked:
            self._lib_message("Marca al menos un archivo.", ERR)
            return
        destination = (
            "la papelera de reciclaje" if trash_available() else "la papelera (si no está disponible, se informará)"
        )
        if not messagebox.askyesno("Eliminar", f"¿Enviar {len(picked)} archivo(s) a {destination}?", parent=self):
            return
        deleted, errors = delete_files([item.path for item in picked], self.settings.folders)
        self._finish_library_action(deleted, errors, "eliminados")

    def _clean_leftovers(self) -> None:
        leftovers = list_leftovers(*self.settings.folders)
        if not leftovers:
            self._lib_message("No hay archivos temporales. Todo limpio ✨", OK)
            return
        if not messagebox.askyesno(
            "Limpiar temporales", f"¿Borrar {len(leftovers)} archivo(s) .part/.ytdl/.temp?", parent=self
        ):
            return
        deleted, errors = delete_files(leftovers, self.settings.folders, use_trash=False)
        self._finish_library_action(deleted, errors, "temporales borrados")

    def _finish_library_action(self, deleted: int, errors: list[str], what: str) -> None:
        self._refresh_library()
        if errors:
            self._lib_message(f"{deleted} {what}, {len(errors)} con error: {errors[0]}", ERR)
        else:
            self._lib_message(f"{deleted} {what} ✔", OK)

    def open_folders(self) -> None:
        for folder in self.settings.folders:
            try:
                folder.mkdir(parents=True, exist_ok=True)
                open_path(folder)
            except OSError as exc:
                self._lib_message(f"No se pudo abrir {folder}: {exc}", ERR)

    # -------------------------------------------------------------------- ajustes
    def _choose_folder(self, key: str) -> None:
        current = self.settings.music_path if key == "music" else self.settings.video_path
        chosen = filedialog.askdirectory(initialdir=str(current), parent=self)
        if chosen:
            self._apply_folder(key, chosen)

    def _apply_folder(self, key: str, value: str) -> None:
        value = value.strip()
        if not value or self._syncing:
            return
        folder = Path(value).expanduser()
        attribute = "music_folder" if key == "music" else "video_folder"
        if getattr(self.settings, attribute) == str(folder):
            return
        setattr(self.settings, attribute, str(folder))
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Carpeta", f"No se pudo crear la carpeta:\n{folder}\n\n{exc}", parent=self)
        self._persist()

    # ---------------------------------------------------------------------- cierre
    def _on_close(self) -> None:
        self._apply_folder("music", self.set_music_entry.get())
        self._apply_folder("video", self.set_video_entry.get())
        for job in self.jobs:
            if not job.row.finished:
                job.cancel.set()
        self.settings.save()
        self.destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
