"""Runtime settings for things that must NOT live in the repo (secrets) or
that differ per deployment. Everything else stays in main.py's config block.

Resolution order (pydantic-settings): real environment variables first, then a
`.env` file in the working directory. That means one `.env` at the repo root
covers both environments: locally the script reads it directly; on the droplet
docker compose forwards the same file into the container via `env_file:`
(see docker-compose.yml). `.env.sample` documents the keys.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramSettings(BaseSettings):
    bot_token: str = ""
    chat_id: str = ""

    enabled: bool = True
    # ~20 songs/hour would ping subscribers constantly; post silently by default.
    silent: bool = True


class SqliteSettings(BaseSettings):
    # Where songs land (the file is created on first run). A relative path
    # resolves against the working directory: repo root locally, /data
    # (= host ./data/) under Docker.
    db_path: str = "songs.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_ignore_empty=False,
        extra="ignore",
    )

    telegram: TelegramSettings = TelegramSettings()
    sqlite: SqliteSettings = SqliteSettings()


settings = Settings()
