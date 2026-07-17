# CLAUDE.md

Context for Claude Code working on this repo. Read the gotchas section before
touching anything that talks to YouTube or does the crop — most of it was
learned the hard way.

## Project

`esc-greatest-hits-song-parser` — a small personal tool that watches the
**"Eurovision Song Contest: Non-Stop Hits!"** YouTube livestream and logs every
song as it plays. Each song is shown in a pink overlay box in the bottom-left of
the video, formatted `Artist - Song - Country Year`
(e.g. `Amir - Jai Cherché - France 2016`). The tool grabs one frame per minute,
reads that box with OCR, appends each new song to a CSV, and (optionally)
posts it to a Telegram channel with a country-flag emoji.

The pipeline lives in **`main.py`** (config-at-top); the Telegram side is
split into small modules (`adapters/`, `core/`, `fixtures/`). It's a
uv-managed Python project; deployment is **Docker Compose** (see README for
the droplet cookbook).

## Commands

- **Calibrate (run first on any new machine/stream):**
  `python main.py --calibrate` (local) or
  `docker compose run --rm logger --calibrate` (droplet).
  Grabs one frame; saves `calibration_frame.png`, `calibration_crop.png`,
  `pink_mask.png`; prints the OCR read, the pink-pixel count, and whether the
  pink auto-tighten hit the box. Use it to tune `CROP_FRAC` and the pink
  thresholds for the current stream resolution.
- **Test Telegram posting:** `python main.py --test-telegram` (local) or
  `docker compose run --rm logger --test-telegram` (droplet). Sends one
  hardcoded sample (`🇫🇷 Amir — J'ai Cherché — France 2016`), prints the API
  response, exits. Verifies token, chat id, and the bot's admin rights end to
  end before going live.
- **Run the logger:** `python main.py` (local, Ctrl-C to stop) or
  `docker compose up -d` + `docker compose logs -f` (droplet). New songs land
  in `songs.csv` — repo root locally, `./data/` under Docker (the container
  runs from `/data`, bind-mounted to `./data`).
- **Deps (uv):**
  `uv add "yt-dlp[default]" pytesseract pillow imagehash numpy pydantic-settings`.
  Keep yt-dlp on nightly: `uv add --prerelease allow "yt-dlp[default]"`.
  The droplet installs from `uv.lock`, so bumping yt-dlp means: bump locally,
  commit `pyproject.toml` + `uv.lock`, then pull + `docker compose up -d --build`
  on the droplet (recipe in README).

## Pipeline (what `run()` does each cycle)

1. `grab_frame()` — `yt-dlp -g` resolves the live stream URL, then ffmpeg grabs
   one current frame as PNG. yt-dlp is invoked as `sys.executable -m yt_dlp`
   (via `YTDLP_CMD`) so it always matches the script's own Python env.
2. `crop_box()` → `find_pink_box()` — build an HSV pink mask inside a search band
   (`CROP_FRAC`), find the box via the longest contiguous run of pink-heavy
   columns/rows, and crop **tight** to it (no background padding).
3. `imagehash.phash` change detection — only OCR when the box actually changes
   (`HASH_THRESHOLD`), so a 3-minute song is read once, not 3 times.
4. `ocr()` — upscale 4×, grayscale, tesseract `--psm 7`, Latin script model.
5. `parse()` → validate → dedup on `(artist, song)` → `append_csv()` with an ISO
   timestamp.
6. Telegram post (best-effort, AFTER the CSV append):
   `services/telegram_service.py` formats `{flag} Artist — Song — Country
   Year` (flags from `fixtures/country_mappings.py`) and sends it through
   `adapters/telegram_client.py`. Any failure is a one-line `[warn]` —
   Telegram must never break the loop; `songs.csv` stays the source of truth.

## Key files

- `main.py` — the vision pipeline + the run loop. Config block is at the top
  and is heavily commented; treat it as the source of truth over this doc.
- `adapters/telegram_client.py` — stdlib-only (`urllib`) Bot API client.
  Plain text on purpose (no `parse_mode` → no escaping); best-effort — warns,
  never raises.
- `services/telegram_service.py` — the Telegram glue `main.py` calls: message
  formatting (flag + em-dashes), client construction from settings, and the
  `--test-telegram` routine.
- `core/settings.py` — pydantic-settings `Settings`: the Telegram knobs, from
  env vars first, then `./.env`.
- `fixtures/country_mappings.py` — normalized country name → ISO alpha-2 →
  flag emoji (computed from regional indicators, no emoji literals); 🇪🇺
  fallback for unknown/OCR-mangled names and defunct states.
- `.env` — Telegram secrets + `TZ` (**secret**, never commit — same rule as
  `cookies.txt`). Lives at the repo root in both environments: locally
  `core/settings.py` reads it directly (optional); under Docker, compose
  forwards it into the container verbatim via `env_file:` and **requires it to
  exist** (`cp .env.sample .env` is the minimum). Edits apply with
  `docker compose up -d` — values are injected at container create, so a
  recreate is enough, no rebuild. Keys are documented in `.env.sample`.
- `Dockerfile` / `docker-compose.yml` — deployment. The image bakes in ffmpeg,
  tesseract (+ Latin model symlink, see gotchas), Deno, and the locked deps;
  compose mounts `./data` as the working dir, forwards `.env` via `env_file:`
  (see gotchas), and sets `restart: unless-stopped`.
- `README.md` — user-facing docs + the DigitalOcean operating cookbook
  (first-time setup, updating, cookie refresh, troubleshooting).
- `songs.csv` — output: `timestamp, artist, song, country, year, raw_text`.
- `cookies.txt` — YouTube session cookies (**secret**, see gotchas). Never
  commit. Lives next to where the script runs: repo root locally,
  `data/cookies.txt` on the droplet.
- `calibration_*.png`, `pink_mask.png` — generated by `--calibrate`. Disposable.
- `debug_caps/` — per-cycle debug screencaps (frame/crop/mask), auto-pruned
  after `DEBUG_KEEP_HOURS`.
- `pyproject.toml` / `uv.lock` / `.venv` — uv project.

Make sure `.gitignore` covers `cookies.txt`, `.env`, `songs.csv`, `data/`,
`debug_caps/`, and the calibration PNGs.

## Config knobs (top of the script)

- `VIDEO_URL` — the live stream's `watch?v=...` URL.
- `INTERVAL` (60s), `STREAM_QUALITY` (`best[height<=?1080]`).
- `CROP_FRAC` — the search band (fractions of the frame) for the pink box;
  tuned per resolution via `--calibrate`. `AUTO_TIGHTEN_TO_PINK` tightens to the
  detected box inside it.
- Pink mask: `PINK_H` / `PINK_S_MIN` / `PINK_V_MIN` / `PINK_MIN_PIXELS` /
  `PINK_TRIM_RIGHT_PX`.
- `OCR_LANG = "script/Latin"` — the Latin script model (all European Latin
  diacritics in one model). Same name works everywhere: Homebrew ships it under
  `script/` natively, and the Dockerfile symlinks Debian's root-level model to
  match (see gotchas). Leave it as `"script/Latin"`.
- `HASH_THRESHOLD` — phash distance that counts as "the box changed".
- `DEBUG_SAVE_CAPS` / `DEBUG_DIR` / `DEBUG_KEEP_HOURS` — save every cycle's
  frame/crop/mask for post-mortem debugging; pruned automatically.
- `YTDLP_CMD`, `YTDLP_EXTRA_ARGS` — see gotchas.
- **Telegram** knobs are NOT in `main.py` — they come from env vars / `.env`
  via `core/settings.py`: `TELEGRAM__BOT_TOKEN` (secret), `TELEGRAM__CHAT_ID`,
  `TELEGRAM__ENABLED`, `TELEGRAM__SILENT` (default on — ~20 songs/hour would
  ping subscribers constantly). Note the **double** underscore (see gotchas).
  Missing token/chat id ⇒ one startup `[warn]`, logger runs without posting.
- **`TZ`** — also set in `.env`, but NOT a `core/settings.py` field (and never
  should be): it's read by the C runtime under `datetime.now()`, and
  pydantic-settings only parses `.env` into an object — it doesn't export to
  the process environment. Unset ⇒ container timestamps in UTC; local runs
  always use the system timezone.

## Environments

- **Local dev (primary):** Mac (Apple Silicon), Python 3.11, uv + PyCharm.
  tesseract + tesseract-lang + deno via Homebrew. **Residential IP → the resolve
  works with NO cookies**, but the shared `YTDLP_EXTRA_ARGS` passes
  `./cookies.txt` anyway — keep a copy at the repo root (or drop the flag
  locally).
- **Deployment:** DigitalOcean droplet (`esc-greatest-hits-parser`),
  Ubuntu 24.04, **1 GB RAM + 2 GB swap**, Frankfurt, repo at
  `/root/esc-gh-parser`. Runs via **Docker Compose** —
  `restart: unless-stopped` survives crashes and reboots, so there is no
  systemd unit and none is needed. **Datacenter IP → needs cookies + Deno**
  (see gotchas); both are handled by the image + `data/cookies.txt`.

## Hard-won gotchas (don't re-learn these)

- **A JS runtime is mandatory.** Current yt-dlp needs Deno (or Node) to solve
  YouTube's "n challenge"; without it you get `No video formats found`.
  Locally: Homebrew Deno. In the image: the Dockerfile copies the Deno binary
  to `/usr/local/bin`, so it's always on PATH and no `--js-runtimes` flag is
  needed (that workaround was only ever for bare systemd's minimal PATH).
- **Datacenter IPs need cookies; residential IPs don't.** On the Mac it just
  works. On the droplet you must have `data/cookies.txt` from a logged-in
  (use a **throwaway** Google account) session. Export Netscape `cookies.txt`
  from a browser (private window, Firefox is most reliable), `scp` it over,
  `chmod 600`. Cookies expire/rotate — expect the occasional refresh; no
  restart needed, yt-dlp re-reads the file every cycle. The `data/` mount is
  read-write **on purpose**: yt-dlp writes rotated cookies back, which keeps
  the session alive longer.
- **Don't force a random player client without a JS runtime** — that's what
  caused `No formats` on the Mac. The combo that works with cookies + Deno is
  `--extractor-args "youtube:player-client=default,web_embedded"`.
- **Do NOT re-add `bgutil-ytdlp-pot-provider`.** We tried it; it OOM-killed the
  1 GB droplet (SIGKILL while compiling npm deps) and isn't needed once Deno
  solves the challenge.
- **The 1 GB droplet OOMs the Deno solver** — fixed with a 2 GB swapfile
  (+ `vm.swappiness=10`), made permanent in `/etc/fstab`. Keep the swap; don't
  assume it needs a bigger droplet. (Setup recipe in README.)
- **yt-dlp version drift** (PyCharm vs terminal vs uv): always invoke as
  `sys.executable -m yt_dlp` (already done via `YTDLP_CMD`) so different copies
  can't be picked up. Keep it on nightly. The container's version comes from
  `uv.lock` — rebuilding the image does NOT bump it; update the lockfile
  locally first.
- **Latin model path differs by OS** — Debian/Ubuntu installs it at the
  tessdata root (`"Latin"`), Homebrew/tessdata_fast under `script/`
  (`"script/Latin"`). The Dockerfile symlinks the Debian model into a
  `script/` dir so `OCR_LANG = "script/Latin"` resolves in both environments —
  don't rename it, and keep the symlink if you touch the Dockerfile.
- **Crop tightness:** crop tight to the pink box on ALL sides. Padding into the
  background makes OCR hallucinate a trailing/leading `|`. Trimming into the pink
  on the LEFT also causes a phantom — only `PINK_TRIM_RIGHT_PX` (right side) is
  safe to shave.
- **Search band right edge** must stay left of the "NON-STOP Hits!" logo
  (~0.82 of frame width); the logo is also pink.
- **Telegram env vars use a DOUBLE underscore** (`TELEGRAM__BOT_TOKEN`, not
  `TELEGRAM_BOT_TOKEN`) — `core/settings.py` nests a `telegram` model with
  `env_nested_delimiter="__"`. An early compose file enumerated the
  single-underscore names under `environment:` and Docker ran with posting
  silently disabled (pydantic ignored them and fell back to defaults). That's
  why compose forwards the whole `.env` via `env_file:` instead — one source
  of truth. Don't re-introduce a per-variable `environment:` list.
- **Docker Desktop can't nest a file bind inside a dir bind.** Mounting
  `./cookies.txt:/data/cookies.txt` on top of `./data:/data` fails on virtiofs
  ("mountpoint is outside of rootfs"). That's why cookies live at
  `data/cookies.txt` under Docker rather than being mounted from the repo
  root.

### `YTDLP_EXTRA_ARGS` (confirmed working, same in both environments)

```python
YTDLP_EXTRA_ARGS = ["--cookies", "./cookies.txt",
                    "--extractor-args", "youtube:player-client=default,web_embedded"]
```

The relative `./cookies.txt` resolves to the repo root locally and to `/data`
(= host `./data/`) inside the container, since compose sets the working dir.

## Telegram posting

Every new song is posted to a Telegram channel as
`🇫🇷 Amir — J'ai Cherché — France 2016` (country/year tail omitted when OCR
didn't yield it). Setup steps (BotFather, chat id) are in the README; secrets
go in `.env` (see `.env.sample`), which compose forwards verbatim via
`env_file:` — **never** bake `.env` into the image, and don't enumerate the
variables in `environment:` (see gotchas). `--test-telegram` is the end-to-end
check for this chain, like `--calibrate` is for the vision chain.

- **Custom Telegram emoji: don't re-research this.** Verified against the Bot
  API docs (July 2026): custom emoji in **channel** posts require the bot to
  own a paid Fragment username; the Bot API 9.4 Premium-owner exception covers
  private/group/supergroup chats but deliberately NOT channels. Loophole if it
  ever becomes a must-have: a locked-down supergroup instead of a channel +
  Premium on the bot owner. Until then: standard Unicode flag emoji (they
  render everywhere except Windows desktop, which shows the two-letter code —
  acceptable).
- Posting happens AFTER the CSV append and is best-effort: no retry queue, a
  missed post is just a `[warn]` + `→ post failed` console tag. Rate limits
  are a non-issue (~1 post/3 min vs Telegram's ~1 msg/sec).

## Conventions

- Single file, config-at-top. Prefer editing the config block over the code for
  behavior tweaks.
- `--calibrate` is the main manual test — use it to verify the full chain
  (resolve → frame grab → crop → OCR) end to end after any environment change.
- **No commits or PRs unless explicitly asked.** Leave changes uncommitted in
  the working tree; the user reviews and commits/pushes themselves.

## Roadmap / ideas

- **Fuzzy-match** OCR output against a known list of Eurovision entries to
  auto-correct rare misreads (would also fix flag lookups for OCR-mangled
  country names, which currently fall back to 🇪🇺).
- Retry/queue for failed Telegram posts; backfilling posts from `songs.csv`.
- Consider **SQLite** instead of CSV for easier querying.
- Sync/ship `songs.csv` off the box periodically.
