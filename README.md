# esc-greatest-hits-song-parser

Watches the **"Eurovision Song Contest: Non-Stop Hits!"** YouTube livestream,
OCRs the pink song-title overlay once a minute, and appends every new song to a
CSV. See `CLAUDE.md` for the full pipeline description and gotchas.

## Cookies preparation
1) Check out [this article](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp) to extract cookies from Incpgnito browser session.
2) Run a command like `scp ~/Downloads/cookies.txt root@{IPv4 Droplet address}:/root/cookies.txt` (this one's for Mac) to move ypur locally created cookies file to the DigitalOcean droplet.

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

For the DigitalOcean droplet this same compose file works as-is: clone the
repo, put the cookies at `./data/cookies.txt`, `docker compose up -d` — Deno is
in the image, and `restart: unless-stopped` replaces a systemd service. Keep
the 2 GB swap; the Deno solver still runs inside the container.
