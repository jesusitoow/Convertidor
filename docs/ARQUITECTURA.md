# Arquitectura · YT2MP3 / MediaVault v2.0

## 1. Objetivo

Separar por completo la lógica de negocio de la interfaz para que descarga, organización, configuración y biblioteca sean probables sin abrir ventanas ni acceder a la red. Python 3.12+, `StrEnum`, dataclasses y type hints completos; `mypy --strict` y `ruff` se ejecutan en CI local.

```
┌──────────────────────────────────────────────────────────────┐
│                     app.py (ÚNICA capa UI)                    │
│  CustomTkinter · cola thread-safe · pestañas · eventos after  │
└───────────────┬──────────────────────────┬───────────────────┘
                │ llama a                  │ llama a
                ▼                          ▼
      ┌──────────────────┐        ┌──────────────────┐
      │  downloader.py   │        │    library.py    │
      │  URL → yt-dlp    │        │  FS → biblioteca │
      └────────┬─────────┘        └──────────────────┘
               │ usa
               ▼
      ┌──────────────────┐        ┌──────────────────┐
      │  organizer.py    │◄───────│    config.py     │
      │  reglas puras    │        │  ~/.yt2mp3/json  │
      └──────────────────┘        └──────────────────┘
```

**Regla de oro:** ningún módulo excepto `app.py` importa `customtkinter`, `tkinter` ni muestra ventanas.

## 2. Módulos

### `config.py`
- `Settings` es una dataclass `slots=True` con rutas base universales (`Path.home() / "Downloads" / {"Musica","Videos"}`).
- `load()` tolera archivo ausente, JSON roto, tipos inesperados y valores fuera de rango; migra las claves v1 `folder` y `quality`.
- `save()` escribe de forma atómica (`config.json.tmp` → `config.json`) y solo registra un aviso si falla.
- `ensure_folders()` crea ambas carpetas con `mkdir(parents=True, exist_ok=True)`.

### `organizer.py` (núcleo puro)
- Enums `DownloadMode`, `OrganizeMode`, `VideoQuality`, `Platform` (`StrEnum`).
- `sanitize_component()` elimina `< > : " / \ | ? *`, caracteres de control, `..`, espacios/puntos finales y nombres reservados de Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`), limita a 80 caracteres.
- `genre_from_text()` normaliza acentos (`NFKD`) y usa coincidencia por palabras completas para clasificar en ocho géneros canónicos.
- `genre_name()` prioriza el género manual: si reconoce una palabra clave devuelve la carpeta canónica; si no, respeta el texto del usuario ya sanitizado.
- `detect_platform()` diferencia YouTube, TikTok y otras plataformas por host exacto.
- `resolve_destination()` calcula la carpeta y verifica que siga siendo descendiente de la base antes de crearla.

### `downloader.py`
- `is_supported_url()` valida: esquema `http/https`, sin credenciales, puerto `80/443/None`, host IDNA válido, sin IPs privadas/loopback/link-local/reservadas (`ipaddress.is_global`), sin `localhost`, `.local`, `.internal`, hosts de una etiqueta y sin caracteres de control. Después aplica una **allowlist**: hosts exactos de YouTube/TikTok y dominios/subdominios públicos de Instagram, Facebook, X/Twitter, SoundCloud y Vimeo.
- `find_ffmpeg()` prefiere el FFmpeg del sistema y usa `imageio-ffmpeg` como respaldo.
- `build_options()` construye dos perfiles:
  - Audio: `bestaudio/best`, `FFmpegExtractAudio(mp3, 320/192/128)`, `FFmpegMetadata`, `windowsfilenames=True`.
  - Vídeo: `bestvideo+bestaudio/best` (o variantes `height<=1080/720`), `merge_output_format=mp4`, `FFmpegMetadata`. No se fuerza ningún extractor externo: los extractores nativos de TikTok de `yt-dlp` priorizan el stream sin marca de agua cuando existe.
- `fetch_metadata()` obtiene título/artista/género en una primera pasada (`skip_download`), lo que permite elegir la carpeta antes de descargar.
- `download()` ejecuta la descarga con hooks de progreso y cancelación (`threading.Event`). Errores tipados: `DownloadCancelled`, `UnsupportedURLError`.

### `library.py`
- `list_media(*folders)` escanea recursivamente con `rglob`, ignora enlaces simbólicos, devuelve `MediaFile` con `kind`, `category` (ruta relativa o `Directo`) y `source`.
- `list_leftovers()` encuentra `.part`, `.ytdl`, `.temp` de forma recursiva.
- `delete_files()` exige que cada archivo esté `is_relative_to()` alguna raíz permitida, sea regular, no enlace y tenga suficiente permitido. Si `Send2Trash` no está disponible, **informa del error en lugar de borrar permanentemente**.
- `open_path()` usa `os.startfile` / `open` / `xdg-open` según plataforma.

### `app.py`
- `App(ctk.CTk)` con `CTkTabview`: **Descargar**, **Biblioteca**, **Ajustes**.
- `JobRow` encapsulates título, estado, barra, velocidad y botón `✕`.
- `Job` + `UIEvent` + dos `queue.Queue`: los workers (2) hacen red/disco; los eventos se aplican en el hilo de la UI mediante `after(100, _poll)`. Ningún worker toca widgets.
- El worker: cancelación → metadatos → carpeta destino → descarga → evento `done`/`error`/`cancelled`.
- **Limpiar lista** elimina solo filas en estado terminal; nunca toca archivos.
- La biblioteca muestra tipo, categoría, tamaño y botones `▶`/`📂`, selección múltiple, envío a papelera y limpieza de temporales.

## 3. Flujo de una descarga

```
UI: submit() → valida cada línea con is_supported_url()
             → crea Job(request, base, organize_mode, manual_genre, row)
             → jobs_q.put(job)
Worker:      → fetch_metadata(url)
             → resolve_destination(base, mode, metadata, manual_genre, platform)
             → download(replace(request, destination=...), hooks, cancel)
UI (_poll):  → "preparando" → "descargando" → progreso %/velocidad
             → "convirtiendo" → "Completado" | "Error" | "Cancelado"
```

La cancelación es cooperativa: `job.cancel.set()` hace que el hook de `yt-dlp` lance `DownloadCancelled` en el próximo evento, y que la descarga termine limpiamente.

## 4. Decisiones de seguridad

| Riesgo | Mitigación |
| --- | --- |
| `file://`, `javascript:`, `ftp://` | Allowlist de esquema en `is_supported_url`. |
| SSRF a `localhost`/IP privada | `ipaddress.is_global`, bloqueo de hosts de una etiqueta, `.local`, `.internal`, puertos no estándar. |
| Dominio fraudulento `youtube.com.evil.com` | Comparación por host exacto o sufijo de dominio, nunca por substring. |
| *Path traversal* en género/artista | `sanitize_component()` + `resolve_destination()` verifica `is_relative_to`. |
| Nombres inválidos en Windows | `windowsfilenames=True` y limpieza de caracteres reservados. |
| Borrado fuera de carpeta | `resolve()` + `is_relative_to()` + sufijo permitido + rechazo de symlinks. |
| Pérdida accidental de archivos | La papelera es obligatoria para borrado normal; los temporales se borran directo. |
| Configuración corrupta | Defaults seguros y escritura atómica. |

## 5. Extensión

- **Nueva plataforma**: añade hosts en `organizer.py` (`*_HOSTS` o `OTHER_PLATFORM_DOMAINS`). La validación y la detección se actualizan juntas; no toques la UI.
- **Nuevo género**: añade la entrada a `GENRE_KEYWORDS` en `organizer.py` y, si hace falta, al catálogo `GENRES`.
- **Nueva calidad de vídeo**: añade valor a `VideoQuality` y su `VIDEO_QUALITY_LABELS`; la UI se genera dinámicamente desde esos mapas.
- **Nuevo campo de ajuste**: añade el campo a `Settings`; `load()`/`save()` y la validación de tipos funcionan automáticamente.
- **Otro frontend (CLI, web)**: reutiliza `config`, `organizer`, `downloader` y `library` sin cambios; solo implementa su propia capa de presentación.

## 6. Verificación

```bash
pytest                 # 90 pruebas, sin red ni GUI
ruff check .           # lint
mypy yt2mp3 tests      # tipado estricto
python -m yt2mp3       # arranque real
```

Los tests de descarga sustituyen `yt_dlp.YoutubeDL` por un doble que dispara los hooks, por lo que son deterministas y no consumen ancho de banda.
