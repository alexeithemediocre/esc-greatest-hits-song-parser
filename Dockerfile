# syntax=docker/dockerfile:1

FROM python:3.14-slim

# System tools the script shells out to / needs:
#   ffmpeg     - grabs one frame from the resolved stream URL
#   tesseract  - OCR; the script-latn package is the Latin script model
#                ("script/Latin", all European Latin diacritics in one model)
#   tzdata     - so TZ= gives songs.csv local timestamps
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        tesseract-ocr \
        tesseract-ocr-script-latn \
        tzdata \
    && rm -rf /var/lib/apt/lists/* \
    # Debian installs the model at the tessdata root ("Latin"), but the script
    # uses the Homebrew-style name "script/Latin" -- symlink so both resolve.
    && tessdata="$(dirname "$(find /usr/share/tesseract-ocr -name 'Latin.traineddata' | head -1)")" \
    && mkdir -p "$tessdata/script" \
    && ln -s ../Latin.traineddata "$tessdata/script/Latin.traineddata"

# yt-dlp needs a JS runtime on PATH to solve YouTube's "n challenge";
# without one every resolve fails with "No video formats found".
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# uv, pinned to the same minor version used for uv.lock locally.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

# Install locked dependencies first so this layer caches across code edits.
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# NOTE: .env is deliberately NOT copied -- secrets never go into image layers.
# docker compose loads .env at runtime and passes the values via environment:.
COPY main.py ./
COPY adapters/ ./adapters/
COPY core/ ./core/
COPY fixtures/ ./fixtures/
COPY services/ ./services/

# Venv python first on PATH -> sys.executable -m yt_dlp uses the locked yt-dlp.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Run from /data (bind-mounted in compose) so songs.csv, the --calibrate PNGs
# and the relative ./cookies.txt path all resolve to the host, not the image.
WORKDIR /data

ENTRYPOINT ["python", "/app/main.py"]
