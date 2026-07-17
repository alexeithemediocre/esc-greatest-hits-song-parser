"""Telegram posting glue on top of adapters.telegram_client.

main.py only ever talks to TelegramService (build it once, then feed it parsed
song records); the adapter underneath stays a plain Bot API transport. All
configuration -- token, chat id, on/off, silent -- comes from core.settings,
with the keys documented in .env.sample."""

import json
import sys

from adapters.telegram_client import TelegramClient
from core.settings import settings
from fixtures.country_mappings import flag_for


class TelegramService:
    """Formats song records into channel posts and sends them, best-effort:
    with posting off / unconfigured every send is a quiet no-op, and a failed
    send is just a [warn] from the adapter. By post time the CSV append has
    already happened -- songs.csv is the source of truth, and Telegram must
    never break the logging loop."""

    def __init__(self, client: TelegramClient | None = None):
        """Resolve settings into a ready-to-post client, or into
        self.client = None when posting is disabled or the token / chat id
        are missing. The missing-secrets case is a one-line [warn], never a
        crash -- the logger keeps logging to the CSV regardless. Passing a
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

    def send_message_to_channel(self, rec: dict) -> dict | None:
        """Format a parsed song record and post it. Returns the decoded API
        response, or None when posting is off (quiet no-op) or the send
        failed (the adapter has already printed the [warn])."""
        return (
            self.client.send_message_to_channel(self.format_telegram_message(rec))
            if self.client
            else None
        )

    @staticmethod
    def format_telegram_message(rec: dict) -> str:
        """Build the channel post, e.g. "🇫🇷 Amir — J'ai Cherché — France 2016".
        The country/year tail is omitted cleanly when OCR didn't yield it."""
        head = (
            f"{flag_for(rec['country'], rec['year'])} {rec['artist']} — {rec['song']}"
        )
        tail = " ".join(str(part) for part in (rec["country"], rec["year"]) if part)

        return f"{head} — {tail}" if tail else head

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
        print(
            f"Sending test message to {settings.telegram.chat_id}: {self.format_telegram_message(sample)}"
        )
        resp = self.send_message_to_channel(sample)

        if resp is None:
            sys.exit(1)  # the [warn] above already has the details

        print("API response:")
        print(json.dumps(resp, indent=2, ensure_ascii=False))
        print(
            "\nPosted OK -- check that the message (with the 🇫🇷 flag) reached the channel."
        )
