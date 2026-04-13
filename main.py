"""
Discord Media Downscaler v2 — Discord file size compressor.
v2: animated progress bar (PIL gradient + shimmer), glowing drop zone,
    title pulse, status spinner, busy-row color cycling.
"""

import os
import sys
import math
import queue
import threading
import subprocess as _sp
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path


def _open_folder(path: str) -> None:
    """Open *path* in the system file manager — cross-platform."""
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        _sp.Popen(['open', path])
    else:
        _sp.Popen(['xdg-open', path])

from PIL import Image, ImageDraw, ImageTk

# ── FFmpeg init ───────────────────────────────────────────────────────────────
try:
    import imageio_ffmpeg
    _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    _FFMPEG = 'ffmpeg'

import compressor
compressor.FFMPEG_PATH = _FFMPEG

# ── Constants ─────────────────────────────────────────────────────────────────
ALL_EXTS = compressor.IMAGE_EXTS | compressor.VIDEO_EXTS | compressor.AUDIO_EXTS

TIER_LIMITS = {
    '10 MB  (Ultra-safe)':  10 * 1024 * 1024,
    '25 MB  (Free)':        25 * 1024 * 1024,
    '50 MB  (Nitro Basic)': 50 * 1024 * 1024,
    '500 MB (Nitro)':      500 * 1024 * 1024,
}

BG      = '#1e1f22'
BG2     = '#2b2d31'
BG3     = '#313338'
ACCENT  = '#5865f2'
ACCENT2 = '#7289da'
FG      = '#dbdee1'
FG_DIM  = '#80848e'
GREEN   = '#23a559'
GREEN2  = '#57f287'
RED     = '#f23f43'
YELLOW  = '#f0b232'

_SPINNER = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'


# ── Colour helpers ────────────────────────────────────────────────────────────

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def _lerp_hex(c1: str, c2: str, t: float) -> str:
    """Blend two '#rrggbb' colours."""
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return '#{:02x}{:02x}{:02x}'.format(
        int(_lerp(r1, r2, t)),
        int(_lerp(g1, g2, t)),
        int(_lerp(b1, b2, t)),
    )


def fmt_size(n: int) -> str:
    if n < 1024:       return f'{n} B'
    if n < 1024 ** 2:  return f'{n / 1024:.1f} KB'
    if n < 1024 ** 3:  return f'{n / 1024 ** 2:.1f} MB'
    return                    f'{n / 1024 ** 3:.2f} GB'


# ── Animated progress bar ─────────────────────────────────────────────────────

class AnimatedProgressBar(tk.Canvas):
    """
    Canvas-based progress bar with:
    - smooth gradient fill (blurple → purple, or green when done)
    - sliding shimmer stripe
    - pulsing glow when complete
    - subtle idle-trough pulse when at 0
    """

    # Gradient stops: progress bar (active) and done (green)
    _BAR  = ((0x58, 0x65, 0xf2), (0x9b, 0x84, 0xf5))   # blurple → light purple
    _DONE = ((0x1e, 0xa5, 0x59), (0x57, 0xf2, 0x87))    # green   → bright green
    _BG   = (0x1e, 0x1f, 0x22)
    _TR   = (0x31, 0x33, 0x38)   # trough colour

    def __init__(self, parent, **kw):
        h  = kw.pop('height', 10)
        self._bar_width = kw.pop('bar_width', 476)
        super().__init__(parent, height=h, width=self._bar_width,
                         bd=0, highlightthickness=0, bg=BG, **kw)
        self._progress  = 0.0
        self._phase     = 0.0   # shimmer sweep 0→1
        self._glow_ph   = 0.0   # done-glow pulse 0→1
        self._idle_ph   = 0.0   # idle trough pulse 0→1
        self._is_done   = False
        self._photo     = None
        self._img_id    = None
        self._cache     = None  # (progress, is_done, w, h) → PIL Image
        self._alive     = True
        self.bind('<Configure>', lambda _: setattr(self, '_cache', None))
        self._tick()

    def set_progress(self, pct: float):
        prev_done = self._is_done
        self._progress = max(0.0, min(100.0, float(pct)))
        self._is_done  = self._progress >= 99.9
        if self._is_done != prev_done:
            self._cache = None   # invalidate gradient cache on state change

    def _tick(self):
        if not self._alive:
            return
        self._phase   = (self._phase   + 0.038) % 1.0
        self._glow_ph = (self._glow_ph + 0.022) % 1.0
        self._idle_ph = (self._idle_ph + 0.018) % 1.0
        self._render()
        self.after(16, self._tick)

    def _render(self):
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 2:
            return

        fill_w = max(0, int(w * self._progress / 100.0))
        cache_key = (self._progress, self._is_done, w, h)

        # Rebuild base gradient only when progress / size / state changes
        if self._cache is None or self._cache[0] != cache_key:
            base = self._build_base(w, h, fill_w)
            self._cache = (cache_key, base)
        else:
            base = self._cache[1]

        img = base.copy()
        draw = ImageDraw.Draw(img)

        if fill_w >= 2 and not self._is_done:
            # — Shimmer stripe —
            sx = int(self._phase * (fill_w + 70)) - 35
            for dx in range(-32, 32):
                x = sx + dx
                if 0 <= x < fill_w:
                    intensity = (1.0 - abs(dx) / 32.0) ** 2 * 0.55
                    t = x / max(fill_w - 1, 1)
                    br = int(_lerp(*[c[0] for c in self._BAR], t))
                    bg = int(_lerp(*[c[1] for c in self._BAR], t))
                    bb = int(_lerp(*[c[2] for c in self._BAR], t))
                    nr = min(255, int(br + intensity * (255 - br)))
                    ng = min(255, int(bg + intensity * (255 - bg)))
                    nb = min(255, int(bb + intensity * (255 - bb)))
                    draw.line([(x, 0), (x, h)], fill=(nr, ng, nb))

            # — Bright leading-edge glow —
            if 0 < fill_w < w:
                for dx in range(5):
                    x = fill_w - 1 - dx
                    if 0 <= x < w:
                        a = (1 - dx / 5) * 0.9
                        t = x / max(fill_w - 1, 1)
                        r = min(255, int(_lerp(*[c[0] for c in self._BAR], t) * (1 - a) + 255 * a))
                        g = min(255, int(_lerp(*[c[1] for c in self._BAR], t) * (1 - a) + 255 * a))
                        b = min(255, int(_lerp(*[c[2] for c in self._BAR], t) * (1 - a) + 220 * a))
                        draw.line([(x, 0), (x, h)], fill=(r, g, b))

        elif self._is_done and fill_w >= w:
            # — Done pulsing green glow —
            pulse = (math.sin(self._glow_ph * 2 * math.pi) + 1) / 2
            spread = max(1, int(w * 0.35 * pulse))
            cx = w // 2
            for dx in range(-spread, spread):
                x = cx + dx
                if 0 <= x < w:
                    t_blend = (1 - abs(dx) / spread) ** 2 * 0.35 * pulse
                    pix = img.getpixel((x, h // 2))
                    r = min(255, int(pix[0] * (1 - t_blend) + 0xff * t_blend))
                    g = min(255, int(pix[1] * (1 - t_blend) + 0xff * t_blend))
                    b = min(255, int(pix[2] * (1 - t_blend) + 0x57 * t_blend))
                    draw.line([(x, 0), (x, h)], fill=(r, g, b))

        elif fill_w == 0:
            # — Idle trough pulse —
            pulse = (math.sin(self._idle_ph * 2 * math.pi) + 1) / 2 * 0.18
            tr = self._TR
            c = (
                min(255, int(tr[0] + pulse * 40)),
                min(255, int(tr[1] + pulse * 40)),
                min(255, int(tr[2] + pulse * 40)),
            )
            draw.rectangle([0, 0, w - 1, h - 1], fill=c)

        self._photo = ImageTk.PhotoImage(img)
        if self._img_id is None:
            self._img_id = self.create_image(0, 0, anchor='nw', image=self._photo)
        else:
            self.itemconfig(self._img_id, image=self._photo)

    def _build_base(self, w: int, h: int, fill_w: int) -> Image.Image:
        """Build the static gradient — called only when progress/size/state changes."""
        img = Image.new('RGB', (w, h), self._BG)
        if fill_w <= 0:
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, w - 1, h - 1], fill=self._TR)
            return img

        draw = ImageDraw.Draw(img)
        stops = self._DONE if self._is_done else self._BAR
        # Fill gradient column-by-column
        for x in range(fill_w):
            t = x / max(fill_w - 1, 1)
            r = int(_lerp(stops[0][0], stops[1][0], t))
            g = int(_lerp(stops[0][1], stops[1][1], t))
            b = int(_lerp(stops[0][2], stops[1][2], t))
            draw.line([(x, 0), (x, h)], fill=(r, g, b))

        # Trough remainder
        if fill_w < w:
            draw.rectangle([fill_w, 0, w - 1, h - 1], fill=self._TR)
        return img

    def destroy(self):
        self._alive = False
        super().destroy()


# ── Main App ──────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title('Discord Media Downscaler')
        self.resizable(False, False)
        self.configure(bg=BG)

        self._files: list[str] = []
        self._status: dict[str, str] = {}
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._last_out_dir: str | None = None
        self._compressing = False
        self._auto_open   = tk.BooleanVar(value=True)
        self._current_limit: int = 10 * 1024 * 1024  # updated when compression starts

        # Animation state
        self._anim_frame  = 0
        self._spin_idx    = 0
        self._current_status = 'Ready. Add files and click Compress!'

        self._build_ui()
        self._poll()
        self._master_tick()   # start 60fps animation driver

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._apply_style()

        # Header / title (animated fg)
        self._title_lbl = tk.Label(
            self, text='Discord Media Downscaler',
            bg=BG, fg=FG, font=('Segoe UI', 14, 'bold'),
        )
        self._title_lbl.pack(pady=(12, 2))

        tk.Label(self, text='Compress anything to fit Discord — with minimal quality loss.',
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9)).pack(pady=(0, 8))

        # Drop zone — outer frame holds the animated border
        self._zone_border = tk.Frame(self, bg=BG,
                                     highlightthickness=2,
                                     highlightbackground=BG3)
        self._zone_border.pack(fill='x', padx=12, pady=4)

        self._zone = tk.Frame(self._zone_border, bg=BG2, cursor='hand2', pady=20)
        self._zone.pack(fill='x')

        self._zone_lbl = tk.Label(
            self._zone,
            text='Click here to add files\n(images, video, audio)',
            bg=BG2, fg=FG_DIM, font=('Segoe UI', 11),
        )
        self._zone_lbl.pack(fill='x')

        for w in (self._zone, self._zone_lbl):
            w.bind('<Button-1>', lambda _: self._browse())
            w.bind('<Enter>',    self._zone_enter)
            w.bind('<Leave>',    self._zone_leave)

        # Tier selector
        tier_row = tk.Frame(self, bg=BG)
        tier_row.pack(fill='x', padx=12, pady=4)
        tk.Label(tier_row, text='Limit:', bg=BG, fg=FG_DIM,
                 font=('Segoe UI', 9)).pack(side='left', padx=(0, 6))
        self._tier = tk.StringVar(value='10 MB  (Ultra-safe)')
        for label in TIER_LIMITS:
            tk.Radiobutton(
                tier_row, text=label, variable=self._tier, value=label,
                bg=BG, fg=FG, selectcolor=BG3,
                activebackground=BG, activeforeground=FG,
                font=('Segoe UI', 9),
            ).pack(side='left', padx=3)

        # File queue (Treeview)
        tree_frame = tk.Frame(self, bg=BG)
        tree_frame.pack(fill='both', expand=True, padx=12, pady=4)

        self._tree = ttk.Treeview(
            tree_frame,
            columns=('name', 'size', 'status'),
            show='headings', height=9,
            selectmode='extended',
            style='DMD.Treeview',
        )
        self._tree.heading('name',   text='File')
        self._tree.heading('size',   text='Size')
        self._tree.heading('status', text='Status')
        self._tree.column('name',   width=255, anchor='w',      stretch=False)
        self._tree.column('size',   width=110, anchor='center', stretch=False)
        self._tree.column('status', width=150, anchor='w',      stretch=False)
        self._tree.tag_configure('done',  foreground=GREEN)
        self._tree.tag_configure('error', foreground=RED)
        self._tree.tag_configure('busy',  foreground=YELLOW)
        self._tree.tag_configure('warn',  foreground='#f0a030')

        vsb = ttk.Scrollbar(tree_frame, orient='vertical',
                            command=self._tree.yview,
                            style='DMD.Vertical.TScrollbar')
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        # Buttons
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill='x', padx=12, pady=6)

        def mk(text, cmd, accent=False):
            return tk.Button(
                btn_row, text=text, command=cmd,
                bg=ACCENT if accent else BG3, fg=FG,
                relief='flat', padx=12, pady=6, cursor='hand2',
                font=('Segoe UI', 9, 'bold' if accent else 'normal'),
                activebackground='#4752c4' if accent else BG2,
                activeforeground=FG,
            )

        self._btn_add    = mk('+ Add Files',  self._browse)
        self._btn_clear  = mk('Clear',        self._clear)
        self._btn_go     = mk('Compress!',    self._start, accent=True)
        self._btn_cancel = mk('Cancel',       self._cancel)
        self._btn_open   = mk('Open Output',  self._open_output)

        for b in (self._btn_add, self._btn_clear, self._btn_go,
                  self._btn_cancel, self._btn_open):
            b.pack(side='left', padx=3)

        self._btn_cancel.configure(state='disabled', fg=FG_DIM,
                                   activeforeground=FG_DIM)

        # Auto-open checkbox
        auto_row = tk.Frame(self, bg=BG)
        auto_row.pack(fill='x', padx=14, pady=(2, 0))
        tk.Checkbutton(
            auto_row,
            text='Auto-open output folder when done',
            variable=self._auto_open,
            bg=BG, fg=FG_DIM, selectcolor=BG3,
            activebackground=BG, activeforeground=FG,
            font=('Segoe UI', 9),
        ).pack(side='left')

        # Animated progress bar (custom Canvas)
        self._progbar = AnimatedProgressBar(self, height=10, bar_width=496)
        self._progbar.pack(padx=12, pady=(4, 2), fill='x')

        # Status label
        self._status_var = tk.StringVar(value=self._current_status)
        tk.Label(self, textvariable=self._status_var,
                 bg=BG, fg=FG_DIM, font=('Segoe UI', 9),
                 anchor='w').pack(fill='x', padx=14, pady=(0, 10))

        self.update_idletasks()
        self.geometry('520x630')

    def _apply_style(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        s.configure('DMD.Treeview',
                    background=BG3, fieldbackground=BG3, foreground=FG,
                    rowheight=24, borderwidth=0, relief='flat')
        s.configure('DMD.Treeview.Heading',
                    background=BG2, foreground=FG_DIM, relief='flat',
                    font=('Segoe UI', 9, 'bold'))
        s.map('DMD.Treeview',
              background=[('selected', ACCENT)],
              foreground=[('selected', '#ffffff')])
        s.configure('DMD.Vertical.TScrollbar',
                    background=BG2, troughcolor=BG3, arrowcolor=FG_DIM)

    # ── Drop zone hover ───────────────────────────────────────────────────────

    def _zone_enter(self, _=None):
        self._zone.configure(bg='#36373d')
        self._zone_lbl.configure(bg='#36373d')

    def _zone_leave(self, _=None):
        self._zone.configure(bg=BG2)
        self._zone_lbl.configure(bg=BG2)

    # ── Master animation tick (60 fps) ────────────────────────────────────────

    def _master_tick(self):
        f = self._anim_frame
        self._anim_frame += 1

        # ① Title pulse (every 3 frames ≈ 20 fps)
        if f % 3 == 0:
            ph = (math.sin(f * 0.012) + 1) / 2   # 0→1 slow wave
            color = _lerp_hex('#c4c9f0', ACCENT2, ph * 0.55)
            self._title_lbl.configure(fg=color)

        # ② Drop zone border glow (every 2 frames ≈ 30 fps)
        if f % 2 == 0:
            if self._compressing:
                # Steady accent glow while compressing
                ph = (math.sin(f * 0.08) + 1) / 2
                border_col = _lerp_hex(ACCENT, '#9b84f5', ph)
            elif self._files:
                # Gentle pulse when files are queued
                ph = (math.sin(f * 0.05) + 1) / 2
                border_col = _lerp_hex(BG3, ACCENT, ph * 0.45)
            else:
                border_col = BG3
            self._zone_border.configure(highlightbackground=border_col)

        # ③ Status spinner (every 5 frames ≈ 12 fps) — only while compressing
        if f % 5 == 0 and self._compressing:
            self._spin_idx = (self._spin_idx + 1) % len(_SPINNER)
            spin = _SPINNER[self._spin_idx]
            self._status_var.set(f'{spin}  {self._current_status}')

        # ④ Busy-row colour pulse in Treeview (every 2 frames ≈ 30 fps)
        if f % 2 == 0 and self._compressing:
            ph = (math.sin(f * 0.18) + 1) / 2
            busy_col = _lerp_hex(YELLOW, '#ffd966', ph)
            self._tree.tag_configure('busy', foreground=busy_col)

        # ⑤ Compress button pulse while active (every 3 frames)
        if f % 3 == 0:
            if self._compressing:
                ph = (math.sin(f * 0.10) + 1) / 2
                btn_col = _lerp_hex(ACCENT, '#7983f5', ph)
                self._btn_go.configure(bg=btn_col)
            else:
                self._btn_go.configure(bg=ACCENT)

        self.after(16, self._master_tick)

    # ── File management ───────────────────────────────────────────────────────

    def _browse(self):
        ext_str = ' '.join('*' + e for e in sorted(ALL_EXTS))
        paths = filedialog.askopenfilenames(
            title='Select files to compress',
            filetypes=[('Supported media', ext_str), ('All files', '*.*')],
        )
        for p in paths:
            self._add_file(p)

    def _add_file(self, path: str):
        path = str(Path(path).resolve())
        if path in self._files:
            return
        ext = Path(path).suffix.lower()
        if ext not in ALL_EXTS:
            messagebox.showwarning(
                'Unsupported type',
                f'{Path(path).name}\n\nFile type {ext!r} is not supported.',
            )
            return
        self._files.append(path)
        self._status[path] = 'queued'
        self._tree.insert(
            '', 'end', iid=path,
            values=(Path(path).name, fmt_size(os.path.getsize(path)), 'Queued'),
        )
        self._set_status(f'{len(self._files)} file(s) queued.')

    def _clear(self):
        if self._worker and self._worker.is_alive():
            messagebox.showinfo('Busy', 'Cancel the current job first.')
            return
        self._files.clear()
        self._status.clear()
        for row in self._tree.get_children():
            self._tree.delete(row)
        self._progbar.set_progress(0)
        self._last_out_dir = None
        self._set_status('Ready. Add files and click Compress!')

    def _set_status(self, msg: str):
        """Update status text (spinner will be prepended during compression)."""
        self._current_status = msg
        if not self._compressing:
            self._status_var.set(msg)

    # ── Compression ───────────────────────────────────────────────────────────

    def _start(self):
        if not self._files:
            messagebox.showinfo('Nothing to do', 'Add some files first.')
            return
        if self._worker and self._worker.is_alive():
            messagebox.showinfo('Busy', 'Already compressing.')
            return

        limit = TIER_LIMITS[self._tier.get()]
        self._current_limit = limit
        self._stop.clear()
        self._compressing = True
        self._progbar.set_progress(0)

        for p in self._files:
            if self._status.get(p) != 'done':
                self._tree.item(p, values=(
                    Path(p).name,
                    fmt_size(os.path.getsize(p)),
                    'Queued',
                ), tags=())
                self._status[p] = 'queued'

        self._btn_go.configure(state='disabled')
        self._btn_cancel.configure(state='normal', fg=FG, activeforeground=FG)
        self._set_status('Starting...')

        self._worker = threading.Thread(
            target=self._worker_fn,
            args=(list(self._files), limit),
            daemon=True,
        )
        self._worker.start()

    def _cancel(self):
        self._stop.set()
        self._set_status('Cancelling...')

    def _open_output(self):
        if self._last_out_dir and os.path.isdir(self._last_out_dir):
            _open_folder(self._last_out_dir)
        else:
            messagebox.showinfo('No output yet',
                                'Compress something first, then click this.')

    # ── Worker thread ─────────────────────────────────────────────────────────

    def _worker_fn(self, paths: list[str], limit: int):
        total = len(paths)
        for idx, path in enumerate(paths):
            if self._stop.is_set():
                self._q.put(('global_status', 'Cancelled.'))
                break

            self._q.put(('item_status', path, 'Working…', 'busy'))

            def _cb(pct, msg, _i=idx, _p=path):
                overall = (_i / total * 100) + (pct / total)
                self._q.put(('progress', overall, msg))
                self._q.put(('item_status', _p, msg[:30], 'busy'))

            try:
                out  = compressor.compress_file(path, limit, _cb, self._stop)
                size = os.path.getsize(out) if os.path.exists(out) else 0
                self._last_out_dir = str(Path(out).parent)
                met_limit = size <= limit
                self._q.put(('item_done', path, out, size, None, met_limit))
            except InterruptedError:
                self._q.put(('item_done', path, None, 0, 'Cancelled', False))
                break
            except Exception as exc:
                self._q.put(('item_done', path, None, 0, str(exc)[:40], False))

        self._q.put(('all_done',))

    # ── Queue poll ────────────────────────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                self._handle(self._q.get_nowait())
        except queue.Empty:
            pass
        self.after(50, self._poll)

    def _handle(self, msg):
        kind = msg[0]

        if kind == 'progress':
            _, pct, text = msg
            self._progbar.set_progress(min(99.0, pct))  # 100 reserved for all_done
            self._set_status(text)

        elif kind == 'item_status':
            _, path, text, tag = msg
            if self._tree.exists(path):
                vals = self._tree.item(path, 'values')
                self._tree.item(path,
                                values=(vals[0], vals[1], text),
                                tags=(tag,))

        elif kind == 'item_done':
            _, path, out_path, out_size, error, met_limit = msg
            if not self._tree.exists(path):
                return
            name = Path(path).name
            orig = os.path.getsize(path)
            if error:
                self._tree.item(path,
                                values=(name, fmt_size(orig), f'✗ {error}'),
                                tags=('error',))
                self._status[path] = 'error'
            elif met_limit:
                savings = int((1 - out_size / orig) * 100) if orig > 0 else 0
                status_text = f'Done ✓ -{savings}%' if savings > 0 else 'Done ✓ (no change)'
                self._tree.item(path,
                                values=(name,
                                        f'{fmt_size(orig)} → {fmt_size(out_size)}',
                                        status_text),
                                tags=('done',))
                self._status[path] = 'done'
            else:
                limit_str = fmt_size(self._current_limit)
                status_text = f'⚠ Best effort: {fmt_size(out_size)} (target {limit_str})'
                self._tree.item(path,
                                values=(name,
                                        f'{fmt_size(orig)} → {fmt_size(out_size)}',
                                        status_text),
                                tags=('warn',))
                self._status[path] = 'warn'

        elif kind == 'global_status':
            self._set_status(msg[1])

        elif kind == 'all_done':
            self._compressing = False
            self._progbar.set_progress(100)
            self._btn_go.configure(state='normal', bg=ACCENT)
            self._btn_cancel.configure(state='disabled',
                                       fg=FG_DIM, activeforeground=FG_DIM)
            self._tree.tag_configure('busy', foreground=YELLOW)
            done  = sum(1 for v in self._status.values() if v == 'done')
            warn  = sum(1 for v in self._status.values() if v == 'warn')
            error = sum(1 for v in self._status.values() if v == 'error')
            parts: list[str] = []
            if done:  parts.append(f'{done} compressed')
            if warn:  parts.append(f'{warn} best effort (see ⚠ items)')
            if error: parts.append(f'{error} failed')
            self._set_status(
                (', '.join(parts) or 'Done')
                + ' — click "Open Output" to find your files.'
            )
            if self._auto_open.get() and self._last_out_dir and os.path.isdir(self._last_out_dir):
                _open_folder(self._last_out_dir)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app = App()
    app.mainloop()
