"""SQLite persistence glue on top of adapters.sqlite_client.

main.py only ever talks to SqliteService (build it once, provision the table
at startup, then feed it parsed song records); the adapter underneath stays a
plain SQL transport. The db path comes from core.settings (SQLITE__DB_PATH,
documented in .env.sample), same as the Telegram knobs. This replaced
append_csv() -- the database is now the source of truth that the Telegram
post is best-effort AFTER."""

import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from adapters.sqlite_client import SqliteClient
from core.settings import settings

# "Central European time" for humans: Europe/Berlin tracks CET/CEST including
# the DST flips, which a fixed UTC+1 offset would get wrong half the year.
_CENTRAL_EUROPEAN = ZoneInfo("Europe/Berlin")


class SqliteService:
    def __init__(self, client: SqliteClient | None = None):
        """Build a client for the settings-configured db path (the file is
        created on first use). Passing a pre-built `client` skips the
        construction (mirrors TelegramService). An empty SQLITE__DB_PATH is
        fatal rather than a fallback: sqlite3 would treat "" as a nameless
        TEMPORARY database and silently discard every song on exit."""
        if client:
            self.client = client

            return

        if not settings.sqlite.db_path:
            sys.exit(
                "[fatal] SQLITE__DB_PATH is set but empty -- give it a real "
                "path or drop the key to get the default (see .env.sample)."
            )

        self.client = SqliteClient(settings.sqlite.db_path)

    def provision_table(self) -> None:
        """Create the songs table if it doesn't exist. Call once at startup."""
        self.client.provision_table()

    def add_entry_to_db(self, rec: dict) -> None:
        """Persist one parsed song record, stamped with the current time.
        Timestamps are stored in UTC for correctness -- one canonical clock
        regardless of the host's timezone -- and converted to a display
        timezone only on the way out (see get_entry_occurrences_in_db)."""
        self.client.add_entry_to_db(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            artist=rec["artist"],
            song=rec["song"],
            country=rec["country"],
            year=rec["year"],
            raw_text=rec["raw"],
        )

    def get_entry_occurrences_in_db(
        self, country: str, year: int
    ) -> tuple[int, datetime | None]:
        """How many times the (country, year) entry has been logged, and when
        it last played, in Central European time (the stream's home zone).
        Returns (0, None) for a first-timer. Query BEFORE add_entry_to_db()
        when "last played" should mean the previous spin, not the current one.
        """
        timestamps = self.client.get_entry_occurrences_in_db(country, year)

        if not timestamps:
            return 0, None

        last_seen = datetime.fromisoformat(timestamps[-1]).astimezone(_CENTRAL_EUROPEAN)

        return len(timestamps), last_seen
