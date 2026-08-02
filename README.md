# Discord Media Downscaler

Compress images, video, and audio to fit Discord's file size limit with as
little quality loss as the limit allows. Supports every tier: 10 MB, 25 MB
free, 50 MB Nitro Basic, 500 MB Nitro.

Drop a file in, pick your limit, get a file back that fits. No account, no
upload, no server. Everything runs on your machine.

**Platforms:** Windows, Linux, macOS. Pre-built binaries, no Python install
needed.
**Android port:** [discord-media-downscaler-android](https://github.com/JakobS1900/discord-media-downscaler-android)

---

## Download

Grab a binary from [Releases](../../releases/latest):

| Platform | File |
|---|---|
| Windows | `DiscordMediaDownscaler-windows.exe` |
| Linux | `DiscordMediaDownscaler-linux` |
| macOS (Apple Silicon) | `DiscordMediaDownscaler-macos` |

**Windows:** double-click it.

**Linux:**
```bash
chmod +x DiscordMediaDownscaler-linux
./DiscordMediaDownscaler-linux
```

**macOS:** the binary is unsigned, so Gatekeeper blocks it the first time.
Either right-click the file in Finder, choose Open, then Open again in the
dialog, or clear the quarantine flag from a terminal:
```bash
xattr -d com.apple.quarantine DiscordMediaDownscaler-macos
chmod +x DiscordMediaDownscaler-macos
./DiscordMediaDownscaler-macos
```
One-time step. It launches normally after that.

---

## How the compression actually works

The interesting part is not calling FFmpeg. It is hitting a hard byte ceiling
without throwing away more quality than you have to, on media you have never
seen before.

**Images: binary search on quality, not a fixed guess.**
JPEG and WebP quality has a non-linear relationship to output size, and it
differs per image, so a fixed quality setting either overshoots the limit or
wastes half of it. Instead the encoder binary-searches the quality value, at
most 14 probes, and stops early once a result lands within 85% of the limit.
That last condition matters: without it the search keeps going for a result
that is a rounding error smaller, at the cost of visible quality.

When quality bottoms out at 1 and the file is still too big, dimensions halve
and the search restarts. PNG tries lossless first, then falls back to WebP if
the image has alpha, or JPEG if it does not.

**Video: two-pass H.264 down a resolution ladder.**
The target bitrate is computed from the actual limit and the actual duration
rather than guessed. Audio takes a share of that budget scaled to how tight
the total is: 128 kbps when there is room, dropping to 16 kbps mono when there
is not, because at a very tight budget every kbps spent on audio is taken
directly from the picture.

Each resolution step gets five encoding attempts backing off to 40% of the
calculated bitrate, because two-pass rate control undershoots on some content
and overshoots on others. If a step cannot fit, the ladder drops a rung:
original, 1280, 854, 640, 480, 360, 240, then 240 at reduced framerate, then
finally 240 with audio stripped. It stops at the first result that fits,
since two-pass has already optimized quality at that bitrate.

If nothing on the ladder fits, it returns the smallest file it produced rather
than failing, and says so.

**Audio: bitrate search, stereo before mono.**
Same binary search, on bitrate, quantized to 8 kbps steps. Stereo is tried
across the whole range first, and mono only if stereo cannot fit, because
halving the channels is a bigger perceptual hit than a moderate bitrate drop.
Lossless sources (WAV, FLAC) convert to Opus, which is the right codec for
low bitrates.

**Throughout:** metadata is stripped from every output (`-map_metadata -1`,
and a clean pixel copy for images), so location and camera data from your
phone do not travel with the file. Video gets `+faststart` so it plays before
it has finished downloading. Long encodes are cancellable, and cancelling
terminates the FFmpeg process rather than orphaning it.

| Media | Method |
|---|---|
| JPEG | Binary-search Pillow quality 1-95, then halve dimensions |
| PNG | Lossless first, then WebP (alpha) or JPEG (no alpha) |
| WebP | Binary-search quality |
| Animated GIF | FFmpeg palettegen and paletteuse, then a width ladder |
| Video | Two-pass libx264 with bitrate backoff and a resolution ladder |
| Audio (lossy) | Binary-search bitrate, MP3 or Vorbis |
| Audio (lossless) | Opus, stereo then mono |

---

## Run from source

Python 3.9 or newer. On Linux you also need `python3-tk`
(`sudo apt install python3-tk`).

```bash
git clone https://github.com/JakobS1900/discord-media-downscaler.git
cd discord-media-downscaler

bash install.sh          # Linux and macOS: creates a venv, installs deps
bash run.sh

# Windows:
# python -m venv venv && venv\Scripts\pip install -r requirements.txt
# python main.py
```

## Build your own binary

```bash
bash build.sh            # Linux and macOS -> dist/DiscordMediaDownscaler
build.bat                # Windows         -> dist/DiscordMediaDownscaler.exe
```

Releases are built in CI. See
[`.github/workflows/build.yml`](.github/workflows/build.yml) for the matrix
that produces all three platform binaries.

---

## Dependencies

- [Pillow](https://pillow.readthedocs.io/) for image processing
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) which ships a
  self-contained FFmpeg, so users do not have to install it
- [PyInstaller](https://pyinstaller.org/) for single-binary packaging, build only

## License

MIT. See [LICENSE](LICENSE).
