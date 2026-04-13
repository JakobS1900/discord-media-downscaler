"""
Core compression logic for Discord Media Downscaler.
All media types: images (Pillow), video + audio (FFmpeg via imageio-ffmpeg).
"""

import os
import re
import sys
import time
import shutil
import threading
import subprocess
from io import BytesIO
from pathlib import Path

# Set by main.py after imageio-ffmpeg init
FFMPEG_PATH: str = 'ffmpeg'

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
VIDEO_EXTS = {'.mp4', '.mov', '.webm', '.mkv', '.avi'}
AUDIO_EXTS = {'.mp3', '.ogg', '.wav', '.flac', '.aac', '.m4a'}

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
_NULL_DEVICE      = 'NUL' if sys.platform == 'win32' else '/dev/null'


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_output_path(input_path: str, ext: str = None) -> str:
    """Return <dir>/<stem>_discord<ext>, falling back to Downloads if read-only."""
    p = Path(input_path)
    out_ext = ext or p.suffix
    out_name = p.stem + '_discord' + out_ext
    out_dir = p.parent

    try:
        probe = out_dir / '.dmd_probe'
        probe.touch()
        probe.unlink()
    except (PermissionError, OSError):
        out_dir = Path.home() / 'Downloads'
        out_dir.mkdir(exist_ok=True)

    # Avoid clobbering the source file
    out_path = out_dir / out_name
    if out_path.resolve() == p.resolve():
        out_path = out_dir / (p.stem + '_discord2' + out_ext)
    return str(out_path)


def _run(args: list, stop_event: threading.Event = None) -> tuple[int, bytes]:
    """Run FFmpeg, returning (returncode, stderr_bytes). Supports cancellation."""
    proc = subprocess.Popen(
        [FFMPEG_PATH] + args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=_CREATE_NO_WINDOW,
    )
    stderr_chunks = []

    def _reader():
        for chunk in iter(lambda: proc.stderr.read(4096), b''):
            stderr_chunks.append(chunk)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    while proc.poll() is None:
        if stop_event and stop_event.is_set():
            proc.terminate()
            proc.wait()
            raise InterruptedError('Cancelled by user')
        time.sleep(0.15)

    t.join(timeout=2)
    return proc.returncode, b''.join(stderr_chunks)


def probe_media(path: str) -> dict:
    """
    Probe media file using `ffmpeg -i`. Parses stderr for:
    duration, width, height, has_audio, codec.
    """
    _, stderr = _run(['-i', path])
    text = stderr.decode('utf-8', errors='replace')

    info = {'duration': 0.0, 'width': 0, 'height': 0,
            'has_audio': False, 'codec': 'unknown'}

    # Duration: HH:MM:SS.ss
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', text)
    if m:
        h, mi, s = m.groups()
        info['duration'] = int(h) * 3600 + int(mi) * 60 + float(s)

    # Video stream — codec, WxH
    m = re.search(r'Stream #\S+.*?Video:\s*(\w+).*?(\d{2,5})x(\d{2,5})', text)
    if m:
        info['codec'] = m.group(1)
        info['width'] = int(m.group(2))
        info['height'] = int(m.group(3))

    # Audio stream presence
    if re.search(r'Stream #\S+.*?Audio:', text):
        info['has_audio'] = True

    return info


# ─── Dispatch ─────────────────────────────────────────────────────────────────

def compress_file(path: str, limit_bytes: int,
                  progress_cb=None, stop_event: threading.Event = None) -> str:
    """
    Compress *path* to fit within *limit_bytes*.
    Returns the output file path. Raises on failure / cancellation.
    progress_cb(pct: int, msg: str) is called during processing.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f'File not found: {path}')

    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return _compress_image(path, limit_bytes, progress_cb, stop_event)
    if ext in VIDEO_EXTS:
        return _compress_video(path, limit_bytes, progress_cb, stop_event)
    if ext in AUDIO_EXTS:
        return _compress_audio(path, limit_bytes, progress_cb, stop_event)
    raise ValueError(f'Unsupported file type: {ext}')


# ─── Images ───────────────────────────────────────────────────────────────────

def _compress_image(path, limit_bytes, progress_cb, stop_event):
    from PIL import Image

    if os.path.getsize(path) <= limit_bytes:
        out = get_output_path(path)
        shutil.copy2(path, out)
        if progress_cb:
            progress_cb(100, 'Already fits — copied')
        return out

    ext = Path(path).suffix.lower()
    img = Image.open(path)
    is_animated = getattr(img, 'n_frames', 1) > 1

    if is_animated and ext == '.gif':
        return _compress_gif(path, limit_bytes, progress_cb, stop_event)

    # Strip metadata: create a clean copy
    clean = Image.new(img.mode, img.size)
    clean.putdata(list(img.getdata()))
    has_alpha = img.mode in ('RGBA', 'LA', 'PA') or (
        img.mode == 'P' and 'transparency' in img.info
    )

    if ext == '.png':
        buf = BytesIO()
        clean.save(buf, format='PNG', compress_level=9, optimize=True)
        if buf.tell() <= limit_bytes:
            out = get_output_path(path, '.png')
            Path(out).write_bytes(buf.getvalue())
            if progress_cb:
                progress_cb(100, 'PNG optimized')
            return out
        if has_alpha:
            return _webp_search(clean, path, limit_bytes, progress_cb, stop_event)
        return _jpeg_search(clean.convert('RGB'), path, limit_bytes,
                            progress_cb, stop_event, note='PNG→JPEG lossy fallback')

    if ext in ('.jpg', '.jpeg'):
        return _jpeg_search(clean.convert('RGB'), path, limit_bytes,
                            progress_cb, stop_event)

    if ext == '.webp':
        return _webp_search(clean, path, limit_bytes, progress_cb, stop_event)

    # Fallback: JPEG
    return _jpeg_search(clean.convert('RGB'), path, limit_bytes,
                        progress_cb, stop_event)


def _jpeg_search(img, original_path, limit_bytes, progress_cb, stop_event, note=''):
    """Binary-search JPEG quality to fit within limit_bytes."""
    from PIL import Image

    lo, hi = 1, 95
    best: bytes | None = None
    label = f' ({note})' if note else ''
    scale = 1.0

    for i in range(14):
        if stop_event and stop_event.is_set():
            raise InterruptedError('Cancelled by user')

        q = (lo + hi) // 2
        if progress_cb:
            progress_cb(int(i / 14 * 85), f'Image quality {q}%{label}')

        work = img
        if scale < 1.0:
            w, h = int(img.width * scale), int(img.height * scale)
            work = img.resize((w, h), Image.LANCZOS)

        buf = BytesIO()
        work.save(buf, format='JPEG', quality=q, optimize=True)
        size = buf.tell()

        if size <= limit_bytes:
            best = buf.getvalue()
            if size >= limit_bytes * 0.85:
                break
            lo = q + 1
        else:
            hi = q - 1

        if lo > hi:
            # Stuck at quality=1 and still over — halve dimensions
            if q == 1 and size > limit_bytes and scale > 0.0625:
                scale *= 0.5
                lo, hi = 1, 95
            else:
                break

    out = get_output_path(original_path, '.jpg')
    if best is None:
        # Emergency last attempt at q=1
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=1, optimize=True)
        best = buf.getvalue()

    Path(out).write_bytes(best)
    if progress_cb:
        progress_cb(100, 'Image compressed')
    return out


def _webp_search(img, original_path, limit_bytes, progress_cb, stop_event):
    """Binary-search WebP quality to fit within limit_bytes."""
    lo, hi = 1, 95
    best: bytes | None = None

    for i in range(14):
        if stop_event and stop_event.is_set():
            raise InterruptedError('Cancelled by user')

        q = (lo + hi) // 2
        if progress_cb:
            progress_cb(int(i / 14 * 85), f'WebP quality {q}%')

        buf = BytesIO()
        img.save(buf, format='WEBP', quality=q)
        size = buf.tell()

        if size <= limit_bytes:
            best = buf.getvalue()
            if size >= limit_bytes * 0.85:
                break
            lo = q + 1
        else:
            hi = q - 1

        if lo > hi:
            break

    out = get_output_path(original_path, '.webp')
    if best is None:
        buf = BytesIO()
        img.save(buf, format='WEBP', quality=1)
        best = buf.getvalue()

    Path(out).write_bytes(best)
    if progress_cb:
        progress_cb(100, 'WebP compressed')
    return out


def _compress_gif(path, limit_bytes, progress_cb, stop_event):
    """Compress animated GIF via FFmpeg palettegen + optional scale."""
    out = get_output_path(path, '.gif')

    # Try progressively smaller widths (None = original size)
    widths = [None, 640, 480, 360, 240]

    for idx, width in enumerate(widths):
        if stop_event and stop_event.is_set():
            raise InterruptedError('Cancelled by user')

        label = f'{width}px wide' if width else 'original size'
        if progress_cb:
            progress_cb(int(idx / len(widths) * 85), f'GIF: trying {label}')

        scale_part = f'scale={width}:-1:flags=lanczos,' if width else ''
        vf = (f'{scale_part}split[s0][s1];'
              '[s0]palettegen=max_colors=128[p];'
              '[s1][p]paletteuse=dither=bayer:bayer_scale=5')

        _run(['-y', '-i', path, '-vf', vf, out], stop_event)

        if os.path.exists(out) and os.path.getsize(out) <= limit_bytes:
            if progress_cb:
                progress_cb(100, f'GIF compressed ({label})')
            return out

    if progress_cb:
        progress_cb(100, 'GIF: best effort')
    return out


# ─── Video ────────────────────────────────────────────────────────────────────

# Resolution ladder: (vf_scale_arg, human_label)
# None means original resolution. Framerate-reduced steps are used last-resort.
_RESOLUTION_STEPS = [
    (None,        'original size'),
    ('1280:-2',   '1280px wide'),
    ('854:-2',    '854px wide'),
    ('640:-2',    '640px wide'),
    ('480:-2',    '480px wide'),
    ('360:-2',    '360px wide'),
    ('240:-2',    '240px wide'),
    ('240:-2,fps=15', '240px @ 15fps'),
    ('240:-2,fps=10', '240px @ 10fps'),
]


def _pick_audio_kbps(total_budget_kbps: int) -> tuple[int, bool]:
    """Return (audio_kbps, force_mono) given the total budget in kbps."""
    if total_budget_kbps >= 160:
        return 128, False
    if total_budget_kbps >= 80:
        return 64, False
    if total_budget_kbps >= 40:
        return 32, False
    return 16, True   # very tight budget — mono helps halve audio size


def _compress_video(path, limit_bytes, progress_cb, stop_event):
    if os.path.getsize(path) <= limit_bytes:
        out = get_output_path(path, '.mp4')
        shutil.copy2(path, out)
        if progress_cb:
            progress_cb(100, 'Already fits — copied')
        return out

    info = probe_media(path)
    duration = info['duration']
    has_audio = info['has_audio']

    if not duration or duration < 0.1:
        return _video_fallback(path, limit_bytes, progress_cb, stop_event, has_audio)

    best_effort_path: str | None = None
    best_effort_size: int = 2 ** 62

    steps = _RESOLUTION_STEPS[:]
    # Final pass: try without audio if we still can't fit
    if has_audio:
        steps.append(('240:-2,fps=10', '240px @ 10fps (no audio)'))

    for step_idx, (scale_filter, label) in enumerate(steps):
        if stop_event and stop_event.is_set():
            raise InterruptedError('Cancelled by user')

        # Strip audio only on the very last appended step
        strip_audio = (not has_audio) or (step_idx == len(steps) - 1 and has_audio)

        if progress_cb and step_idx > 0:
            progress_cb(
                int(step_idx / len(steps) * 90),
                f'Still too large — trying {label}...',
            )

        winner, effort, effort_size = _video_twopass(
            path, limit_bytes, duration,
            has_audio and not strip_audio,
            scale_filter, label, progress_cb, stop_event,
            step_idx, len(steps),
        )

        if winner:
            return winner   # hit the target — done

        if effort and effort_size < best_effort_size:
            best_effort_path = effort
            best_effort_size = effort_size

    # Nothing reached the limit — return smallest result we achieved
    if progress_cb:
        mb = best_effort_size / 1024 / 1024
        progress_cb(99, f'Best effort: {mb:.1f} MB (target not fully reached)')
    return best_effort_path or get_output_path(path, '.mp4')


def _video_twopass(path, limit_bytes, duration, has_audio,
                   scale_filter, res_label, progress_cb, stop_event,
                   step_idx, total_steps):
    """
    Two-pass H.264 encoding targeting limit_bytes.
    Returns (winner_path, best_effort_path, best_effort_size).
    winner_path is set only when a result fits within limit_bytes.
    best_effort_path is the smallest file produced regardless.
    """
    import tempfile, os as _os

    out = get_output_path(path, '.mp4')

    # Build video filter — handle fps= suffix in scale_filter
    if scale_filter and 'fps=' in scale_filter:
        vf_args = ['-vf', scale_filter]
    elif scale_filter:
        vf_args = ['-vf', f'scale={scale_filter}']
    else:
        vf_args = []

    # Dynamic audio bitrate based on total budget
    total_budget = int((limit_bytes * 8) / duration / 1000 * 0.95)
    audio_kbps, audio_mono = _pick_audio_kbps(total_budget) if has_audio else (0, False)
    if has_audio:
        audio_ch = ['-ac', '1'] if audio_mono else []
        audio_args = ['-c:a', 'aac', '-b:a', f'{audio_kbps}k', *audio_ch]
    else:
        audio_args = ['-an']

    # Initial video target: total budget minus audio share
    video_kbps = max(8, total_budget - audio_kbps)

    tmp_dir = tempfile.mkdtemp(prefix='dmd_')
    passlog = _os.path.join(tmp_dir, 'ffpass')

    winner: str | None = None
    effort_path: str | None = None
    effort_size: int = 2 ** 62

    try:
        # 5 backoff attempts: 100% → 85% → 70% → 55% → 40% of calculated bitrate
        backoff_factors = [1.0, 0.85, 0.70, 0.55, 0.40]
        n_attempts = len(backoff_factors)

        for attempt, factor in enumerate(backoff_factors):
            if stop_event and stop_event.is_set():
                raise InterruptedError('Cancelled by user')

            kbps = max(8, int(video_kbps * factor))

            # Progress within this resolution step
            step_frac = step_idx / total_steps
            next_frac = (step_idx + 1) / total_steps
            pct_base = int((step_frac + attempt / n_attempts * (next_frac - step_frac)) * 90)

            scan_msg = (
                f'Scanning video ({res_label})...'
                if attempt == 0
                else f'Adjusting — re-scanning ({res_label})...'
            )
            if progress_cb:
                progress_cb(pct_base, scan_msg)

            # Clean passlog before each attempt
            for f in Path(tmp_dir).glob('ffpass*'):
                try:
                    f.unlink()
                except OSError:
                    pass

            rc1, _ = _run([
                '-y', '-i', path,
                *vf_args,
                '-c:v', 'libx264', '-b:v', f'{kbps}k',
                '-preset', 'medium',
                '-pass', '1', '-passlogfile', passlog,
                '-an', '-f', 'null', _NULL_DEVICE,
            ], stop_event)

            if rc1 != 0:
                continue

            enc_msg = (
                f'Encoding at {kbps} kbps ({res_label})...'
                if attempt == 0
                else f'Re-encoding at {kbps} kbps ({res_label})...'
            )
            if progress_cb:
                progress_cb(pct_base + max(1, int((next_frac - step_frac) * 90 / n_attempts / 2)),
                            enc_msg)

            rc2, _ = _run([
                '-y', '-i', path,
                *vf_args,
                '-c:v', 'libx264', '-b:v', f'{kbps}k',
                '-preset', 'medium',
                '-pass', '2', '-passlogfile', passlog,
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                '-map_metadata', '-1',
                '-threads', '0',
                *audio_args,
                out,
            ], stop_event)

            if rc2 != 0:
                continue

            if not (_os.path.exists(out) and _os.path.getsize(out) > 512):
                continue

            size = _os.path.getsize(out)

            # Track the best (smallest) result regardless of limit
            if size < effort_size:
                effort_path = out
                effort_size = size

            if size <= limit_bytes:
                winner = out
                break   # First fit is good enough — two-pass already optimises quality

    finally:
        for f in Path(tmp_dir).glob('ffpass*'):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            _os.rmdir(tmp_dir)
        except OSError:
            pass

    return winner, effort_path, effort_size


def _video_fallback(path, limit_bytes, progress_cb, stop_event, has_audio):
    """Single-pass CRF fallback when duration is unknown."""
    out = get_output_path(path, '.mp4')
    audio_args = ['-c:a', 'aac', '-b:a', '128k'] if has_audio else ['-an']

    for crf in [28, 35, 42, 51]:
        if stop_event and stop_event.is_set():
            raise InterruptedError('Cancelled by user')
        if progress_cb:
            progress_cb(int(crf / 51 * 85), f'Video: CRF {crf} (unknown duration)')

        _run([
            '-y', '-i', path,
            '-c:v', 'libx264', '-crf', str(crf), '-preset', 'medium',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            '-map_metadata', '-1',
            *audio_args,
            out,
        ], stop_event)

        if os.path.exists(out) and os.path.getsize(out) <= limit_bytes:
            if progress_cb:
                progress_cb(100, 'Video compressed')
            return out

    return out


# ─── Audio ────────────────────────────────────────────────────────────────────

def _compress_audio(path, limit_bytes, progress_cb, stop_event):
    if os.path.getsize(path) <= limit_bytes:
        out = get_output_path(path)
        shutil.copy2(path, out)
        if progress_cb:
            progress_cb(100, 'Already fits — copied')
        return out

    ext = Path(path).suffix.lower()
    is_lossless = ext in ('.wav', '.flac')
    info = probe_media(path)
    duration = info['duration']

    if not duration or duration < 0.1:
        return _encode_audio_to(path, get_output_path(path, _audio_out_ext(ext, is_lossless)),
                                128, is_lossless, mono=False, stop_event=stop_event)

    target_kbps = int((limit_bytes * 8) / duration / 1000 * 0.97)
    target_kbps = max(16, min(320, (target_kbps // 8) * 8))

    if progress_cb:
        progress_cb(10, f'Audio: targeting {target_kbps} kbps')

    out_ext = _audio_out_ext(ext, is_lossless)
    final_out = get_output_path(path, out_ext)
    best_kbps: int | None = None
    best_mono = False

    import tempfile as _tmp_mod

    # Try stereo first, then mono if stereo can't hit the limit
    for mono in (False, True):
        lo, hi = 16, 320
        found_kbps: int | None = None
        kbps = target_kbps
        suffix = ' (mono)' if mono else ''

        for i in range(9):
            if stop_event and stop_event.is_set():
                raise InterruptedError('Cancelled by user')
            if progress_cb:
                progress_cb(int(i / 9 * 70) + 10, f'Audio: {kbps} kbps{suffix}')

            # Encode to a temp file with the correct extension so FFmpeg knows the format
            tmp_fd, tmp = _tmp_mod.mkstemp(suffix=out_ext, prefix='dmd_audio_')
            os.close(tmp_fd)
            os.unlink(tmp)  # FFmpeg will create it; we just needed a valid path

            _encode_audio_to(path, tmp, kbps, is_lossless,
                             mono=mono, stop_event=stop_event)

            if not os.path.exists(tmp) or os.path.getsize(tmp) < 512:
                hi = kbps - 8
            else:
                size = os.path.getsize(tmp)
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                if size <= limit_bytes:
                    found_kbps = kbps
                    if size >= limit_bytes * 0.85:
                        break
                    lo = kbps + 8
                else:
                    hi = kbps - 8

            if lo > hi:
                break
            kbps = max(16, ((lo + hi) // 2 // 8) * 8)

        if found_kbps is not None:
            best_kbps = found_kbps
            best_mono = mono
            break  # Stereo worked — no need to try mono

    # Final encode at the best bitrate we found
    lbl = ' (-> Opus OGG)' if is_lossless else ''
    if best_kbps is not None:
        if progress_cb:
            progress_cb(90, f'Audio: final encode at {best_kbps} kbps')
        _encode_audio_to(path, final_out, best_kbps, is_lossless,
                         mono=best_mono, stop_event=stop_event)
    else:
        # Best effort: minimum bitrate mono
        if progress_cb:
            progress_cb(90, 'Audio: best effort (minimum bitrate)')
        _encode_audio_to(path, final_out, 16, is_lossless,
                         mono=True, stop_event=stop_event)

    if progress_cb:
        progress_cb(100, f'Audio compressed{lbl}')
    return final_out


def _audio_out_ext(src_ext: str, is_lossless: bool) -> str:
    if is_lossless:
        return '.ogg'
    if src_ext in ('.mp3', '.aac', '.m4a'):
        return '.mp3'
    return '.ogg'


def _encode_audio_to(path, out, kbps, is_lossless, mono: bool = False, stop_event=None):
    """Encode audio to *out* at *kbps* bitrate. Returns *out* path."""
    ext = Path(path).suffix.lower()
    channels = ['-ac', '1'] if mono else []

    if is_lossless:
        _run([
            '-y', '-i', path,
            '-c:a', 'libopus', '-b:a', f'{kbps}k',
            *channels, '-ar', '48000',
            '-map_metadata', '-1',
            out,
        ], stop_event)
    elif ext in ('.mp3', '.aac', '.m4a'):
        _run([
            '-y', '-i', path,
            '-c:a', 'libmp3lame', '-b:a', f'{kbps}k',
            *channels,
            '-map_metadata', '-1',
            out,
        ], stop_event)
    else:
        _run([
            '-y', '-i', path,
            '-c:a', 'libvorbis', '-b:a', f'{kbps}k',
            *channels,
            '-map_metadata', '-1',
            out,
        ], stop_event)

    return out
