"""Thin SQLite persistence client -- stdlib only (sqlite3).

No ORM: the logger does exactly three things with the database (create one
table, insert a row, look up past plays of one song), so SQLAlchemy would be
all dependency and no benefit -- same call as adapters/telegram_client.py.

Unlike the Telegram adapter this one is NOT best-effort: the database is the
source of truth (it replaced songs.csv), so a failed write must surface as an
exception instead of being swallowed as a [warn].
"""

import sqlite3


class SqliteClient:
    """Owns the connection and the SQL; everything above that (timestamps,
    record unpacking, timezone maths) belongs in services/sqlite_service.py."""

    def __init__(self, db_path: str):
        # One long-lived connection: the run loop is single-threaded and this
        # process is the only writer. sqlite3 creates the file if missing.
        self._conn = sqlite3.connect(db_path)

    def provision_table(self) -> None:
        """Create the songs table on first run; a no-op ever after."""
        with self._conn:  # commits on success, rolls back on error
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS songs (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,  -- ISO 8601, UTC ("+00:00")
                    artist    TEXT    NOT NULL,
                    song      TEXT    NOT NULL,
                    country   TEXT,
                    year      INTEGER,
                    raw_text  TEXT
                )
                """)

    def add_entry_to_db(
        self,
        timestamp: str,
        artist: str,
        song: str,
        country: str | None,
        year: int | None,
        raw_text: str,
    ) -> None:
        """Insert one logged song (the same columns songs.csv used to hold)."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO songs (timestamp, artist, song, country, year, raw_text)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (timestamp, artist, song, country, year, raw_text),
            )

    def get_entry_occurrences_in_db(self, country: str, year: int) -> list[str]:
        """Timestamps of every logged play of the (country, year) entry,
        oldest first (insertion order, which is also time order). Eurovision
        has one entry per country per year, so the pair identifies a song even
        when OCR fumbles a letter of the artist or title."""
        rows = self._conn.execute(
            "SELECT timestamp FROM songs WHERE country = ? AND year = ? ORDER BY id",
            (country, year),
        ).fetchall()

        return [row[0] for row in rows]
