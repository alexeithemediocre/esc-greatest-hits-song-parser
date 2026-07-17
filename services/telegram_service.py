"""Telegram posting glue on top of adapters.telegram_client.

main.py only ever talks to TelegramService (build it once, then feed it parsed
song records); the adapter underneath stays a plain Bot API transport. All
configuration -- token, chat id, on/off, silent -- comes from core.settings,
with the keys documented in .env.sample."""

import json
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from adapters.telegram_client import TelegramClient
from core.settings import settings
from fixtures.country_mappings import flag_for


class TelegramService:
    """Formats song records into channel posts and sends them, best-effort:
    with posting off / unconfigured every send is a quiet no-op, and a failed
    send is just a [warn] from the adapter. By post time the DB insert has
    already happened -- songs.db is the source of truth, and Telegram must
    never break the logging loop."""

    def __init__(self, client: TelegramClient | None = None):
        """Resolve settings into a ready-to-post client, or into
        self.client = None when posting is disabled or the token / chat id
        are missing. The missing-secrets case is a one-line [warn], never a
        crash -- the logger keeps logging to the DB regardless. Passing a
        pre-built `client` skips the construction but not those two gates."""
        if not settings.telegram.enabled:
            self.client = None

            return

        if not settings.telegram.bot_token or not settings.telegram.chat_id:
            print(
                "[warn] telegram: enabled, but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID "
                "are not set -- running without posting (see .env.sample)."
            )
            self.client = None

            return

        self.client = (
            client
            if client
            else TelegramClient(
                settings.telegram.bot_token,
                settings.telegram.chat_id,
                silent=settings.telegram.silent,
            )
        )

    def is_initialized(self) -> bool:
        """True when a client was built, i.e. posting is on and configured."""
        return bool(self.client)

    def send_message_to_channel(
        self, rec: dict, occurrences: tuple[int, datetime | None] | None = None
    ) -> dict | None:
        """Format a parsed song record and post it. Returns the decoded API
        response, or None when posting is off (quiet no-op) or the send
        failed (the adapter has already printed the [warn]).

        `occurrences` is SqliteService.get_entry_occurrences_in_db()'s answer
        for this song, queried BEFORE its own DB insert -- pass None (the
        default) to omit the stats line, e.g. when OCR yielded no country/year
        to look the song up by."""
        return (
            self.client.send_message_to_channel(
                self.format_telegram_message(rec, occurrences)
            )
            if self.client
            else None
        )

    @staticmethod
    def format_telegram_message(
        rec: dict, occurrences: tuple[int, datetime | None] | None = None
    ) -> str:
        """Build the channel post, e.g. "🇫🇷 Amir — J'ai Cherché — France 2016".
        The country/year tail is omitted cleanly when OCR didn't yield it.
        With `occurrences` given, a second line reports how often the song has
        been noticed before (see _format_occurrences_line)."""
        head = (
            f"{flag_for(rec['country'], rec['year'])} {rec['artist']} — {rec['song']}"
        )

        tail = " ".join(str(part) for part in (rec["country"], rec["year"]) if part)
        message = f"{head} — {tail}" if tail else head

        if occurrences is None:
            return message

        return f"{message}\n{TelegramService._format_occurrences_line(occurrences)}"

    @staticmethod
    def _format_occurrences_line(occurrences: tuple[int, datetime | None]) -> str:
        """The stats line under the song: "Noticed 3 times before, last seen at
        14/07/2026 21:05 CEST (2 days, 14 minutes ago)", with singular "1 time"
        and a "Never noticed before — that's a new one!" greeting for
        first-timers. The zone label comes from the timestamp itself (CET in
        winter, CEST in summer)."""
        count, last_seen = occurrences

        if count == 0 or last_seen is None:
            return "Never noticed before — that's a new one!"

        times = "time" if count == 1 else "times"
        ago = TelegramService._time_ago(datetime.now(timezone.utc) - last_seen)

        return (
            f"Noticed {count} {times} before, last seen at "
            f"{last_seen.strftime('%d/%m/%Y %H:%M')} {last_seen.tzname()} ({ago})"
        )

    @staticmethod
    def _time_ago(delta: timedelta) -> str:
        """Render an elapsed time as "2 days, 3 hours, 5 minutes ago". Days
        and hours appear only when non-zero; minutes always do. A negative
        delta (clock skew) clamps to "0 minutes ago"."""
        total_minutes = max(0, int(delta.total_seconds() // 60))
        days, rest = divmod(total_minutes, 24 * 60)
        hours, minutes = divmod(rest, 60)

        parts = [
            f"{n} {unit}" + ("" if n == 1 else "s")
            for n, unit in (
                (
                    days,
                    "day",
                ),
                (
                    hours,
                    "hour",
                ),
            )
            if n
        ]
        parts.append(f"{minutes} minute" + ("" if minutes == 1 else "s"))

        return ", ".join(parts) + " ago"

    def test_telegram(self) -> None:
        """Manual test for the posting chain (what --calibrate is for the vision
        chain): send one hardcoded sample post, print the API response, exit."""
        if self.client is None:
            sys.exit(
                "[fatal] Telegram is disabled or unconfigured. Set "
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (see .env.sample)."
            )

        sample = {
            "artist": "Amir",
            "song": "J'ai Cherché",
            "country": "France",
            "year": 2016,
        }
        # A fabricated occurrences answer, so the test post shows the stats
        # line exactly as the live loop would render it.
        sample_occurrences = (
            2,
            datetime(2026, 5, 14, 21, 5, tzinfo=ZoneInfo("Europe/Berlin")),
        )
        print(
            f"Sending test message to {settings.telegram.chat_id}:\n"
            f"{self.format_telegram_message(sample, sample_occurrences)}"
        )

        resp = self.send_message_to_channel(sample, sample_occurrences)

        if resp is None:
            sys.exit(1)  # the [warn] above already has the details

        print("API response:")
        print(json.dumps(resp, indent=2, ensure_ascii=False))
        print(
            "\nPosted OK -- check that the message (with the 🇫🇷 flag) reached the channel."
        )
