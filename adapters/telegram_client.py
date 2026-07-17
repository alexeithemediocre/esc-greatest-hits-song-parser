"""Thin Telegram Bot API client -- stdlib only (urllib + json).

No third-party library: the bot does exactly one thing (sendMessage to one
chat), so python-telegram-bot would be all dependency and no benefit.

Messages are sent as plain text, deliberately without parse_mode: song and
artist names are full of '-', "'", '(' that MarkdownV2/HTML would force us to
escape for zero gain.
"""

import json
import urllib.error
import urllib.request


class TelegramClient:
    """Best-effort poster: every failure is a printed "[warn] telegram: ..."
    and a None return, never an exception. By the time we post, the DB insert
    has already happened -- songs.db is the source of truth and Telegram must
    never break the logging loop."""

    def __init__(
        self, bot_token: str, chat_id: str, silent: bool = True, timeout: float = 15.0
    ):
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id
        self.silent = silent
        self.timeout = timeout

    def send_message_to_channel(self, text: str) -> dict | None:
        """Send one plain-text message. Returns the decoded API response on
        success, None on any failure (already reported as a [warn])."""
        payload = json.dumps(
            {
                "chat_id": self.chat_id,
                "text": text,
                "disable_notification": self.silent,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self._api_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as e:
            print(f"  [warn] telegram: HTTP {e.code}: {self._error_description(e)}")
            return None
        except Exception as e:
            print(f"  [warn] telegram: {e}")
            return None

        if not body.get("ok"):
            print(f"  [warn] telegram: {body.get('description', body)}")
            return None

        return body

    @staticmethod
    def _error_description(e: urllib.error.HTTPError) -> str:
        # Telegram's error responses carry a human-readable JSON 'description'
        # (e.g. "Unauthorized", "chat not found") -- surface it if present.
        try:
            return json.load(e).get("description") or str(e.reason)
        except Exception:
            return str(e.reason)
