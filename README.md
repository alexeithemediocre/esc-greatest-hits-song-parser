# esc-gh-parser

Watches the **"Eurovision Song Contest: Non-Stop Hits!"** YouTube livestream,
OCRs the pink song-title overlay once a minute, and appends every new song to a
CSV. See `CLAUDE.md` for the full pipeline description and gotchas.

## Cookies preparation

1) Check out [this article](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)
   to extract cookies from an Incognito browser session (use a **throwaway**
   Google account; Firefox is the most reliable exporter).
2) Copy the exported file to the droplet's `data/` dir (command is for Mac):
   ```bash
   scp ~/Downloads/cookies.txt root@{IPv4 Droplet address}:/root/esc-gh-parser/data/cookies.txt
   ```

## Usage (Docker)

Put your exported YouTube cookies at `./data/cookies.txt` first (needed on
datacenter IPs; harmless elsewhere), then:

```bash
docker compose up -d          # run the logger; songs land in ./data/songs.csv
docker compose logs -f        # watch it
docker compose run --rm logger --calibrate   # the usual end-to-end check
```

Timestamps default to UTC — set `TZ` (e.g. `TZ=Europe/Berlin docker compose up -d`)
if you want local time in the CSV.

## DigitalOcean cookbook

Step-by-step recipes for operating the project on the droplet
(`esc-greatest-hits-parser`, Ubuntu 24.04, 1 GB RAM, Frankfurt). Everything is
done as `root`, with the repo at `/root/esc-gh-parser`.

### Starting this project for the 1st time on DigitalOcean

1. SSH in:
   ```bash
   ssh root@{IPv4 Droplet address}
   ```
2. Make sure the 2 GB swapfile exists — the Deno challenge solver OOMs 1 GB of
   RAM without it. Check with `free -h` (Swap row should say 2.0Gi). On a fresh
   droplet, create it:
   ```bash
   fallocate -l 2G /swapfile && chmod 600 /swapfile
   mkswap /swapfile && swapon /swapfile
   echo '/swapfile none swap sw 0 0' >> /etc/fstab
   sysctl vm.swappiness=10
   echo 'vm.swappiness=10' >> /etc/sysctl.conf
   ```
3. Install Docker (includes the compose plugin):
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
4. Clone the repo:
   ```bash
   cd /root
   git clone <repo-url> esc-gh-parser
   cd esc-gh-parser
   mkdir -p data
   ```
5. Put the YouTube cookies in place — see [Cookies preparation](#cookies-preparation)
   (export locally, `scp` to the droplet), then lock the file down:
   ```bash
   chmod 600 data/cookies.txt
   ```
6. Build and verify the full chain (resolve → frame grab → crop → OCR) once
   before going live:
   ```bash
   docker compose build
   docker compose run --rm logger --calibrate
   ```
   It should print `auto-tighten: HIT the box` and an `OCR currently reads:`
   line with a plausible `Artist - Song - Country Year`. If not, inspect
   `data/calibration_*.png` and `data/pink_mask.png` (see `CLAUDE.md`).
7. Start the logger:
   ```bash
   docker compose up -d
   docker compose logs -f     # Ctrl-C stops watching, not the container
   ```
   `restart: unless-stopped` keeps it running across crashes and droplet
   reboots — no systemd unit needed.

### Pulling & applying git changes on DigitalOcean

1. ```bash
   ssh root@{IPv4 Droplet address}
   cd /root/esc-gh-parser
   git pull
   ```
2. Rebuild and swap in the new container (no-op for services that didn't
   change):
   ```bash
   docker compose up -d --build
   ```
3. Confirm it came back healthy:
   ```bash
   docker compose ps
   docker compose logs -f
   ```
4. Optionally clean up the old image layers:
   ```bash
   docker image prune -f
   ```

### Updating yt-dlp (when YouTube breaks the resolve)

The yt-dlp version is pinned by `uv.lock`, so a droplet rebuild alone will NOT
bump it — the lockfile has to be updated locally first.

1. On your Mac, in the repo:
   ```bash
   uv add --prerelease allow "yt-dlp[default]"
   git add pyproject.toml uv.lock
   git commit -m "bump yt-dlp"
   git push
   ```
2. On the droplet, follow
   [Pulling & applying git changes](#pulling--applying-git-changes-on-digitalocean).

### Refreshing cookies (they expire / rotate)

Symptom: `yt-dlp couldn't resolve the stream` warnings in the logs after weeks
of working fine.

1. Re-export `cookies.txt` locally and `scp` it over — see
   [Cookies preparation](#cookies-preparation).
2. That's it — no restart needed. yt-dlp re-reads `data/cookies.txt` on every
   cycle, so the next minute's grab picks the new cookies up. Check with:
   ```bash
   docker compose logs -f
   ```

### Everyday operations

```bash
docker compose ps                  # is it running?
docker compose logs -f             # live log (one line per minute)
docker compose logs --since 1h     # recent history
docker compose stop                # stop (graceful, same as Ctrl-C)
docker compose up -d               # start again
tail data/songs.csv                # what got logged
```

Fetch the results from your Mac:

```bash
scp root@{IPv4 Droplet address}:/root/esc-gh-parser/data/songs.csv .
```

### Troubleshooting

- **`yt-dlp couldn't resolve the stream` every cycle** — cookies expired
  (→ [Refreshing cookies](#refreshing-cookies-they-expire--rotate)) or yt-dlp
  is too old for YouTube's latest change
  (→ [Updating yt-dlp](#updating-yt-dlp-when-youtube-breaks-the-resolve)).
- **`invalid:` or garbage reads in the log** — the stream layout may have
  changed; run `docker compose run --rm logger --calibrate` and inspect
  `data/calibration_*.png` / `data/pink_mask.png`, then tune `CROP_FRAC` /
  the pink thresholds in `main.py` (see `CLAUDE.md`).
- **Container getting killed / droplet sluggish** — check `free -h`; the 2 GB
  swap must stay (the Deno solver needs it on a 1 GB droplet).
- **Disk filling up over time** — old image layers from rebuilds:
  `docker image prune -f`. Container logs are already capped by the compose
  logging config.
