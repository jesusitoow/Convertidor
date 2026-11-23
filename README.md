<div align="center">

# YT2MP3 · MediaVault v2.0

**Descarga audio MP3 y vídeo MP4 en la máxima calidad, organízalo automáticamente y adminístralo desde una interfaz moderna. Sin terminal, sin dependencias manuales.**

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-7c5cff?style=for-the-badge)
![Engine](https://img.shields.io/badge/engine-yt--dlp%20%2B%20FFmpeg-22c55e?style=for-the-badge)
![Tests](https://img.shields.io/badge/tests-90%20passing-22c55e?style=for-the-badge)
![License](https://img.shields.io/badge/license-MIT-f59e0b?style=for-the-badge)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-64748b?style=for-the-badge)

</div>

---

## ✨ Por qué MediaVault

Una herramienta pensada para uso real: pegas enlaces, eliges calidad y organización, y el archivo aparece exactamente donde debe estar. El resto —validación, metadatos, conversión, cola y limpieza— ocurre detrás de una interfaz limpia.

### Descarga en máxima calidad

- **Audio MP3**: mejor stream disponible (`bestaudio/best`) convertido con FFmpeg a **320 kbps por defecto** (o `192` / `128`) e integrando **metadatos ID3** mediante `FFmpegMetadata`.
- **Vídeo MP4**: `bestvideo+bestaudio` fusionado en contenedor `.mp4` con FFmpeg. Selector de calidad: **Máxima disponible (4K/1080p)**, **1080p** o **720p**.
- **Fuentes**: YouTube, TikTok —con los extractores nativos de `yt-dlp`, que priorizan el stream **sin marca de agua cuando está disponible**—, Instagram, Facebook, X/Twitter, SoundCloud, Vimeo y otras plataformas públicas soportadas.
- **Múltiples enlaces**: pega tantas URLs como quieras, una por línea, y se encolan automáticamente.

### Organización inteligente y universal

Las carpetas base se crean solas y funcionan en cualquier sistema:

```text
~/Downloads/Musica      # MP3
~/Downloads/Videos      # MP4
```

| Modo | Estructura resultante |
| --- | --- |
| **Por Artista / Creador** | `Musica/Bad Bunny/`, `Videos/@creador/` |
| **Por Género Musical** | `Musica/Urbano - Reggaeton/` |
| **Género + Artista** | `Musica/Urbano - Reggaeton/Bad Bunny/` |
| **Directo (sin subcarpetas)** | `Musica/` o `Videos/` |

Géneros reconocidos automáticamente: `Salsa`, `Vallenato`, `Afro - Afrobeats`, `Urbano - Reggaeton`, `Pop`, `Rock`, `Electronica`, `Otros`. La clasificación usa metadatos, etiquetas y título, y admite **género o carpeta manual** cuando quieres forzarla. Los nombres se saneaban con `windowsfilenames=True` y reglas estrictas contra caracteres prohibidos y *path traversal*.

### Interfaz gráfica moderna

- `CustomTkinter` con tema **oscuro / claro / sistema** y pestañas bien estructuradas.
- **Descargar**: caja multilínea, botón *Pegar*, switch *Descargar al pegar*, selectores de tipo/calidad/organización y cola concurrente **thread-safe** con progreso, velocidad, estado y botón `✕` para cancelar. El botón **Limpiar lista** retira las filas terminadas sin borrar archivos.
- **Biblioteca**: escaneo recursivo de `Musica` y `Videos`, nombre/ tipo / categoría / tamaño, ▶ reproducción con la app del sistema, 📂 apertura de carpeta, eliminación segura a la papelera (`Send2Trash`) y limpieza de restos `.part`, `.ytdl` y `.temp`.
- **Ajustes**: carpetas, calidades, organización, apariencia y aviso legal persistentes en `~/.yt2mp3/config.json`.

---

## 🧱 Arquitectura

Separación estricta: **la lógica de negocio jamás importa la interfaz**. `app.py` es el único módulo que conoce `customtkinter`; todo lo demás se puede testear sin ventana ni red.

```text
YT2MP3/
├── yt2mp3/
│   ├── __init__.py       # versión 2.0.0
│   ├── __main__.py       # python -m yt2mp3
│   ├── config.py         # ajustes persistentes y tolerantes a fallos
│   ├── organizer.py      # plataformas, géneros y saneamiento de rutas
│   ├── downloader.py     # validación de URLs + yt-dlp/FFmpeg
│   ├── library.py        # escaneo, apertura y borrado seguro
│   └── app.py            # GUI CustomTkinter + cola thread-safe (única capa UI)
├── tests/                # 90 pruebas unitarias (pytest)
├── docs/                 # ARQUITECTURA.md y capturas
├── launcher.py           # entrypoint para PyInstaller
├── install.bat · run.bat · build_exe.bat
├── pyproject.toml · requirements.txt · requirements-dev.txt
└── LICENSE · README.md
```

Flujo de una descarga: `UI → validar URLs → encolar → fetch_metadata → resolver carpeta → yt-dlp + FFmpeg → eventos → UI`. Los workers nunca tocan widgets: publican eventos inmutables que la interfaz aplica en el hilo principal con `after()`.

La guía completa de decisiones, seguridad y extensión está en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

---

## 🚀 Inicio rápido

### Windows (1 clic)

1. Instala [Python 3.12+](https://www.python.org/downloads/) marcando **Add python.exe to PATH**, o [uv](https://docs.astral.sh/uv/).
2. Doble clic en **`install.bat`** → crea `.venv` e instala dependencias.
3. Doble clic en **`run.bat`** → abre la aplicación.
4. ¿Ejecutable independiente? Ejecuta **`build_exe.bat`** y recoge `dist\YT2MP3.exe`.

### macOS / Linux (consola)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m yt2mp3
```

En Debian/Ubuntu, si tkinter no está disponible:

```bash
sudo apt install python3-tk
```

### Mantener el extractor al día

YouTube y TikTok cambian con frecuencia. Si aparece un error `403` o un formato faltante:

```bash
pip install -U yt-dlp
```

---

## 🔐 Calidad, seguridad y pruebas

**Validación de URLs**: allowlist de esquemas `http/https` y dominios conocidos; bloqueo de `file://`, `javascript:`, `ftp://`, credenciales embebidas, puertos no estándar, `localhost`, IPs privadas/loopback/link-local (SSRF) y dominios falsos tipo `youtube.com.evil.com`.

**Seguridad de archivos**: nombres saneados antes de crear carpetas, verificación `is_relative_to()` antes de borrar, rechazo de enlaces simbólicos, borrado normal hacia la papelera y escritura atómica de la configuración.

**Ingeniería**: type hints completos, `StrEnum`, dataclasses `slots`, `mypy --strict`, Ruff y 90 pruebas deterministas (sin red ni GUI).

```bash
pip install -r requirements-dev.txt
pytest                    # 90 tests
ruff check .              # lint
ruff format --check .     # formato
mypy yt2mp3 tests         # tipado estricto
```

---

## ⚖️ Aviso legal

Esta herramienta debe usarse únicamente con contenido **propio, de dominio público, con licencia libre o con autorización de su autor**. Descargar material protegido por derechos de autor puede infringir los términos del servicio de las plataformas y la legislación aplicable. Eres responsable del uso que le des.

## 📄 Licencia

Distribuido bajo licencia [MIT](LICENSE). © 2026 Jesús Franco.

---

<div align="center">

Construido con [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org/), [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) y [Send2Trash](https://github.com/arsenetar/send2trash).

</div>
