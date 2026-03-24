# Discord Media Downscaler

Compress images, video, and audio to fit Discord's file size limits — with minimal quality loss. Supports all Discord tiers (10 MB, 25 MB Free, 50 MB Nitro Basic, 500 MB Nitro).

## Features

- **Images** — JPEG, PNG, WebP, GIF (including animated): binary-search quality/scale to hit target size
- **Video** — MP4, MOV, WebM, MKV, AVI: two-pass H.264 bitrate targeting; progressive resolution fallback
- **Audio** — MP3, OGG, WAV, FLAC, AAC, M4A: bitrate binary-search; lossless sources convert to Opus OGG
- Animated progress bar, per-file savings percentage, auto-open output folder
- Self-contained binaries — no installation required on Windows, Linux, or macOS

---

## Download (pre-built binaries)

Go to the [Releases](../../releases/latest) page and grab the binary for your platform:

| Platform | File |
|---|---|
| Windows | `DiscordMediaDownscaler-windows.exe` |
| Linux | `DiscordMediaDownscaler-linux` |
| macOS (Apple Silicon) | `DiscordMediaDownscaler-macos` |

### Windows
Double-click `DiscordMediaDownscaler-windows.exe`. That's it.

### Linux
```bash
chmod +x DiscordMediaDownscaler-linux
./DiscordMediaDownscaler-linux
```

### macOS — Gatekeeper notice
The binary is unsigned, so macOS will block it on first launch. Two options:

**Option A — Right-click method (easiest):**
1. Right-click (or Control-click) `DiscordMediaDownscaler-macos` in Finder
2. Select **Open**
3. Click **Open** in the dialog

**Option B — Terminal:**
```bash
xattr -d com.apple.quarantine DiscordMediaDownscaler-macos
chmod +x DiscordMediaDownscaler-macos
./DiscordMediaDownscaler-macos
```

After this one-time step, you can launch it normally.

---

## Run from source

Requires **Python 3.9+**. On Linux, also requires `python3-tk` (`sudo apt install python3-tk`).

```bash
# 1. Clone
git clone https://github.com/JakobS1900/discord-media-downscaler.git
cd discord-media-downscaler

# 2. One-click setup (creates venv, installs deps)
bash install.sh          # Linux / macOS

# Windows (in Command Prompt):
# python -m venv venv && venv\Scripts\pip install -r requirements.txt

# 3. Run
bash run.sh              # Linux / macOS terminal
# macOS Finder: double-click run.command (auto-installs on first launch)
# Windows: python main.py
```

## Build the binary yourself

```bash
bash build.sh            # Linux / macOS  →  dist/DiscordMediaDownscaler
build.bat                # Windows        →  dist/DiscordMediaDownscaler.exe
```

---

## How it works

| Media | Method |
|---|---|
| JPEG | Binary-search Pillow quality (1–95) |
| PNG | Max lossless compression; falls back to WebP (alpha) or JPEG (no alpha) |
| WebP | Binary-search quality |
| Animated GIF | FFmpeg palettegen + paletteuse; scale-down fallback |
| Video | Two-pass H.264 (libx264) bitrate targeting; resolution fallback (1280→854→640px) |
| Audio (lossy) | Binary-search bitrate (MP3/Vorbis) |
| Audio (WAV/FLAC) | Convert to Opus OGG; stereo → mono fallback for tight limits |

---

## Dependencies

- [Pillow](https://pillow.readthedocs.io/) — image processing
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) — self-contained FFmpeg binary
- [PyInstaller](https://pyinstaller.org/) — single-binary packaging (build only)

---

## License

MIT
