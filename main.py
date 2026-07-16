#!/usr/bin/env python3
"""
eurovision_logger.py
====================
Watches the "Eurovision Song Contest: Non-Stop Hits!" YouTube stream, reads the
song name from the pink overlay box in the bottom-left corner once a minute, and
logs each new song to a CSV file.

How it works
------------
1. Every INTERVAL seconds, it pulls ONE current frame from the live stream using
   yt-dlp (to resolve the stream URL) + ffmpeg (to grab a frame). No screen
   capture needed -- works even if the window is minimized or covered.
2. It crops the overlay region, and compares it to the previous crop with a
   perceptual hash. If nothing changed, it does nothing (the same song is still
   playing) -- this avoids re-reading the same song over and over.
3. When the box changes, it runs OCR (tesseract) on the crop, parses the text
   into artist / song / country / year, and -- if it's a new song -- appends a
   row to the CSV with a timestamp.

The OCR + crop + parse pipeline was validated against a real screenshot of the
stream and read "Amir - Jai Cherché - France 2016" perfectly.

Requirements
------------
System tools (install once):
    - yt-dlp      https://github.com/yt-dlp/yt-dlp   (pip install -U yt-dlp)
    - ffmpeg      https://ffmpeg.org/
    - tesseract   https://tesseract-ocr.github.io/
        Linux:  sudo apt install tesseract-ocr tesseract-ocr-fra
        macOS:  brew install tesseract tesseract-lang
        Windows: https://github.com/UB-Mannheim/tesseract/wiki  (add to PATH)

Python packages:
    pip install pytesseract pillow imagehash numpy

Usage
-----
FIRST, calibrate the crop box for YOUR stream resolution:
    python eurovision_logger.py --calibrate
This saves 'calibration_frame.png' (the full frame) and 'calibration_crop.png'
(what the OCR will see). Open both, and if the crop doesn't tightly frame the
pink text box, adjust CROP_FRAC below and re-run --calibrate until it does.

THEN run it for real:
    python eurovision_logger.py
Leave it running in a terminal. Ctrl-C to stop. Songs land in songs.csv.
"""

import argparse
import csv
import io
import os
import re
import subprocess
import sys
import time
from datetime import datetime

from PIL import Image, ImageOps
import pytesseract
import imagehash
import numpy as np

# ------------------------- CONFIG (edit these) ---------------------------------

# The stream. This is the "Non-Stop Hits!" playlist/stream page.
VIDEO_URL = "https://www.youtube.com/watch?v=jP-WZ0w3u70"

# How often to check, in seconds. 60 = once a minute (as you described).
INTERVAL = 60

# Where to save results.
OUTPUT_CSV = "songs.csv"

# Where to look for the overlay, as fractions of the frame (left, top, right,
# bottom). With AUTO_TIGHTEN_TO_PINK on (below), this is just a generous SEARCH
# band -- the script finds the pink box inside it and crops tightly to that, so
# the crop adapts to each song's text length automatically. Make this band a bit
# larger than the biggest box you ever see, but keep the right edge short of the
# "NON-STOP Hits!" logo so its pink text isn't picked up.
CROP_FRAC = (0.043, 0.880, 0.860, 0.932)

# Auto-tighten the crop to the pink box inside CROP_FRAC. Turn off to use the
# CROP_FRAC rectangle verbatim (the old fixed-rectangle behaviour).
AUTO_TIGHTEN_TO_PINK = True

# Pink-box color thresholds, on PIL's 0-255 HSV scale. The box is a hot magenta
# (~hue 220), cleanly clear of the blue stage background (~hue 170). If detection
# misbehaves on your stream, run --calibrate: it saves pink_mask.png so you can
# see exactly what's matched, then nudge these. PINK_H is the (min, max) hue band.
PINK_H = (190, 245)
PINK_S_MIN = 110        # saturation floor -- excludes the white text (near 0 sat)
PINK_V_MIN = 70         # brightness floor
PINK_MIN_PIXELS = 300   # if fewer pink pixels than this, assume no box -> fallback
# The crop hugs the detected pink box tightly on ALL sides -- it never pads into
# the video behind it. A pink<->background edge is exactly what makes OCR
# hallucinate a stray "|", so we never include one; the box's own internal margin
# around the text is plenty. This shaves a couple extra px off the RIGHT only
# (nudge up if a stray symbol ever shows up at the very end of a read).
PINK_TRIM_RIGHT_PX = 1

# Which video quality to fetch. Lower = faster/less bandwidth. 480-720 is plenty
# for reading text and much lighter than 1080p.
STREAM_QUALITY = "best[height<=?1080]"

# Extra yt-dlp arguments to get past YouTube's bot / "not available on this app"
# checks. Find a working combo on the command line first (see below), then paste
# the same flags here. Common ingredients:
#   Cookies from the browser you watch in (helps a LOT with live streams):
#       ["--cookies-from-browser", "firefox"]      # or chrome / edge / brave
#   Force a working player client:
#       ["--extractor-args", "youtube:player_client=web_safari,default"]
# You can combine them:
#   YTDLP_EXTRA_ARGS = ["--cookies-from-browser", "firefox",
#                       "--extractor-args", "youtube:player_client=web_safari,default"]
# Also make sure yt-dlp itself is up to date:  pip install -U --pre "yt-dlp[default]"
YTDLP_EXTRA_ARGS = ["--cookies", "./cookies.txt", "--extractor-args", "youtube:player-client=default,web_embedded"]
# YTDLP_EXTRA_ARGS = []

# How the script invokes yt-dlp. By default it uses the SAME Python that runs
# this script (sys.executable -m yt_dlp). This avoids the classic trap where
# PyCharm's project interpreter has a different / older yt-dlp than the terminal
# you updated -- the script and its yt-dlp are now guaranteed to match.
# If you'd rather point at a specific binary instead, set e.g.:
#   YTDLP_CMD = ["yt-dlp"]                    # first one on PATH
#   YTDLP_CMD = ["/full/path/to/yt-dlp"]      # a specific install
YTDLP_CMD = [sys.executable, "-m", "yt_dlp"]

# Tesseract languages. 'fra' helps with accented French titles like "Cherché".
OCR_LANG = "script/Latin"

# How different the crop must be (perceptual hash distance) to count as "changed".
# Higher = less sensitive to noise. 5 is a good starting point.
HASH_THRESHOLD = 5

# -------------------------------------------------------------------------------


def grab_frame(url: str) -> Image.Image | None:
    """Pull a single current frame from the live stream. Returns a PIL Image."""
    try:
        # Resolve the direct media URL (re-resolved each call so expiring live
        # URLs are never a problem).
        ytdlp_args = [*YTDLP_CMD, *YTDLP_EXTRA_ARGS, "-g", "-v", "-f", STREAM_QUALITY, url]

        # print("running yt-dlp: ", " ".join(ytdlp_args))

        direct = subprocess.run(
            ytdlp_args,
            capture_output=True, text=True, timeout=60,
        )

        if direct.returncode != 0 or not direct.stdout.strip():
            print(f"  [warn] yt-dlp couldn't resolve the stream:\n"
                  f"         {direct.stderr.strip().splitlines()[-1] if direct.stderr.strip() else '(no output)'}")
            return None
        media_url = direct.stdout.strip().splitlines()[-1]

        # Grab the frame nearest the live edge as a PNG on stdout.
        frame = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-i", media_url, "-frames:v", "1", "-f", "image2pipe",
             "-vcodec", "png", "pipe:1"],
            capture_output=True, timeout=90,
        )
        if frame.returncode != 0 or not frame.stdout:
            print(f"  [warn] ffmpeg couldn't grab a frame:\n"
                  f"         {frame.stderr.decode(errors='replace').strip()[:300]}")
            return None
        return Image.open(io.BytesIO(frame.stdout)).convert("RGB")

    except FileNotFoundError as e:
        sys.exit(f"[fatal] Missing tool: {e.filename}. Install yt-dlp and ffmpeg "
                 f"(see the header of this script).")
    except subprocess.TimeoutExpired:
        print("  [warn] Timed out fetching a frame; will retry next cycle.")
        return None


def check_yt_dlp() -> None:
    """Print which yt-dlp the script is actually using, so version mismatches
    (e.g. PyCharm's interpreter vs. your terminal) are obvious. Exits with a
    clear install command if yt-dlp isn't present in THIS environment."""
    try:
        r = subprocess.run([*YTDLP_CMD, "--version"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            print(f"Using yt-dlp {r.stdout.strip()}  (via {' '.join(YTDLP_CMD)})")
            return
    except FileNotFoundError:
        pass
    sys.exit(
        "[fatal] yt-dlp is not available in the Python environment running this "
        "script.\n         This is the environment to install into (note it may "
        "differ from your terminal):\n"
        f'         {sys.executable} -m pip install -U --pre "yt-dlp[default]"'
    )


def _search_region(img: Image.Image):
    """Return (x0, y0, x1, y1) pixel bounds of the CROP_FRAC search band."""
    w, h = img.size
    l, t, r, b = CROP_FRAC
    return int(l * w), int(t * h), int(r * w), int(b * h)


def _pink_mask(rgb: np.ndarray) -> np.ndarray:
    """Boolean mask of pink-box pixels in an RGB array (H,W,3)."""
    hsv = np.asarray(Image.fromarray(rgb).convert("HSV"))
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (H >= PINK_H[0]) & (H <= PINK_H[1]) & (S >= PINK_S_MIN) & (V >= PINK_V_MIN)


def _longest_run(active: np.ndarray):
    """Start/end index of the longest contiguous run of True in a 1-D bool array.
    Used so a solid box wins over stray pink specks (e.g. the logo's edge)."""
    idx = np.where(active)[0]
    if idx.size == 0:
        return None
    groups = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
    g = max(groups, key=len)
    return int(g[0]), int(g[-1])


def find_pink_box(img: Image.Image):
    """Locate the pink overlay inside the search band and return a tight crop of
    it (adapting to the text length). Returns None if no convincing box is found."""
    x0, y0, x1, y1 = _search_region(img)
    region = np.asarray(img.crop((x0, y0, x1, y1)).convert("RGB"))
    mask = _pink_mask(region)
    if mask.sum() < PINK_MIN_PIXELS:
        return None
    h, w = mask.shape
    # A column/row counts as "box" only if a real chunk of it is pink -- this
    # ignores thin noise and anti-aliased edges.
    cols = _longest_run(mask.sum(axis=0) >= max(3, int(0.20 * h)))
    rows = _longest_run(mask.sum(axis=1) >= max(3, int(0.20 * w)))
    if not cols or not rows:
        return None
    c0, c1 = cols
    r0, r1 = rows
    # Hug the pink box tightly on all sides; padding into the background creates
    # phantom "|" characters, so we never include any. c1/r1 are inclusive last
    # pink indices, hence the +1. PINK_TRIM_RIGHT_PX shaves the right a touch more.
    left = x0 + c0
    top = y0 + r0
    right = x0 + min(w, c1 + 1 - PINK_TRIM_RIGHT_PX)
    bottom = y0 + min(h, r1 + 1)
    right = max(right, left + 1)  # guard against inversion if trim is set too high
    return img.crop((left, top, right, bottom))


def crop_box(img: Image.Image) -> Image.Image:
    """The region handed to OCR. Tightens to the detected pink box when enabled,
    otherwise (or if detection fails) falls back to the CROP_FRAC rectangle."""
    if AUTO_TIGHTEN_TO_PINK:
        tight = find_pink_box(img)
        if tight is not None:
            return tight
    x0, y0, x1, y1 = _search_region(img)
    return img.crop((x0, y0, x1, y1))


def ocr(crop: Image.Image) -> str:
    """Read text from the crop. Upscales + grayscales first for cleaner results."""
    big = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
    gray = ImageOps.grayscale(big)
    # --psm 7 = treat the image as a single text line.
    return pytesseract.image_to_string(gray, lang=OCR_LANG, config="--psm 7").strip()


def parse(text: str) -> dict:
    """Split 'Artist - Song - Country Year' into fields. Always keeps raw text."""
    raw = re.sub(r"\s+", " ", text).strip()
    parts = [p.strip() for p in raw.split(" - ")]
    out = {"artist": None, "song": None, "country": None, "year": None, "raw": raw}
    if len(parts) >= 3:
        out["artist"], out["song"], tail = parts[0], parts[1], parts[-1]
        m = re.search(r"(19|20)\d{2}", tail)
        if m:
            out["year"] = int(m.group())
            out["country"] = tail[: m.start()].strip() or None
        else:
            out["country"] = tail
    elif len(parts) == 2:
        out["artist"], out["song"] = parts
    return out


def looks_valid(rec: dict) -> bool:
    """Cheap sanity check so OCR garbage / empty boxes don't get logged."""
    if not rec["raw"] or len(rec["raw"]) < 4:
        return False
    # Need at least an artist and a song separated by ' - '.
    return bool(rec["artist"] and rec["song"])


def append_csv(path: str, rec: dict) -> None:
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["timestamp", "artist", "song", "country", "year", "raw_text"])
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            rec["artist"], rec["song"], rec["country"], rec["year"], rec["raw"],
        ])


def calibrate() -> None:
    check_yt_dlp()
    print("Grabbing one frame to calibrate the crop box...")
    img = grab_frame(VIDEO_URL)
    if img is None:
        sys.exit("Couldn't grab a frame. Check VIDEO_URL and that yt-dlp/ffmpeg work.")
    img.save("calibration_frame.png")

    # Show what the pink detector matched inside the search band.
    x0, y0, x1, y1 = _search_region(img)
    region = np.asarray(img.crop((x0, y0, x1, y1)).convert("RGB"))
    mask = _pink_mask(region)
    Image.fromarray((mask * 255).astype("uint8")).save("pink_mask.png")

    crop = crop_box(img)
    crop.save("calibration_crop.png")
    text = ocr(crop)

    tightened = AUTO_TIGHTEN_TO_PINK and find_pink_box(img) is not None
    print(f"Saved calibration_frame.png ({img.size[0]}x{img.size[1]}), "
          f"calibration_crop.png ({crop.size[0]}x{crop.size[1]}), and pink_mask.png")
    print(f"Pink pixels in search band: {int(mask.sum())}  |  "
          f"auto-tighten: {'HIT the box' if tightened else 'fell back to CROP_FRAC rectangle'}")
    print(f"OCR currently reads: {text!r}")
    print("\nCheck the saved PNGs:")
    print("  - pink_mask.png should show the box as a solid white blob and little")
    print("    else. If it's noisy or empty, adjust PINK_S_MIN / PINK_H / PINK_V_MIN.")
    print("  - calibration_crop.png should hug the pink box. If the search band")
    print("    misses it entirely, widen CROP_FRAC. Then re-run with --calibrate.")


def run() -> None:
    check_yt_dlp()
    print(f"Watching stream every {INTERVAL}s. Logging new songs to {OUTPUT_CSV}. Ctrl-C to stop.\n")
    last_hash = None
    last_song = None  # (artist, song) of the last logged entry, for dedup

    while True:
        cycle_start = time.time()
        img = grab_frame(VIDEO_URL)

        if img is not None:
            crop = crop_box(img)
            h = imagehash.phash(crop)

            stamp = datetime.now().strftime("%H:%M:%S")

            # Only bother with OCR if the box changed since last time.
            if last_hash is None or (h - last_hash) > HASH_THRESHOLD:
                last_hash = h
                rec = parse(ocr(crop))
                stamp = datetime.now().strftime("%H:%M:%S")

                if looks_valid(rec):
                    key = (rec["artist"], rec["song"])

                    if key != last_song:
                        last_song = key
                        append_csv(OUTPUT_CSV, rec)

                        print(f"[{stamp}] + {rec['raw']}")
                    else:
                        print(f"[{stamp}] duplicate?: {rec['raw']}")

                else:
                    print(f"[{stamp}] invalid: {rec['raw']}")

            else:
                print(f"[{stamp}] unchanged. previous hash: {last_hash}, current hash: {h}")

        # Sleep out the remainder of the interval (accounting for time spent).
        elapsed = time.time() - cycle_start
        time.sleep(max(1.0, INTERVAL - elapsed))


def main() -> None:
    ap = argparse.ArgumentParser(description="Log songs from the Eurovision Non-Stop Hits stream.")
    ap.add_argument("--calibrate", action="store_true",
                    help="Grab one frame + crop so you can tune CROP_FRAC, then exit.")
    args = ap.parse_args()

    if args.calibrate:
        calibrate()
        return

    try:
        run()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()



# TODO temporarily store screencaps, for debug purposes. keep them for 24 hours only