from functools import cached_property
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    BOT_TOKEN: str
    ALLOWED_USER_IDS: str  # comma-separated list, parsed via property
    DATABASE_PATH: str = "data/notes.db"

    # Notion integration. NOTION_TOKEN + NOTION_DATABASE_ID (default fallback DB)
    # both required to enable real saves. Per-type DB overrides below — if a
    # type's DB var is unset, the default DB is used.
    NOTION_TOKEN: Optional[str] = None
    NOTION_DATABASE_ID: Optional[str] = None
    NOTION_DB_NOTE: Optional[str] = None
    NOTION_DB_TASK: Optional[str] = None
    NOTION_DB_IDEA: Optional[str] = None
    NOTION_DB_MEETING: Optional[str] = None
    NOTION_DB_1ON1: Optional[str] = None
    NOTION_DB_WORK: Optional[str] = None
    NOTION_DB_PERSONAL: Optional[str] = None

    # OpenAI for classify+format. Empty → llm_processor stub (single 'note' type,
    # body == raw input). Useful for dev without API costs.
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"

    # AssemblyAI Universal-2 для транскрибации голоса/видео.
    # Empty → voice/audio/video handlers отвечают "транскрибация выключена".
    ASSEMBLYAI_API_KEY: Optional[str] = None
    ASSEMBLYAI_SPEECH_MODEL: str = "universal"  # universal | nano | slam-1
    # Force a language ("ru", "en"). None → autodetect (ненадёжно для <30 сек).
    FORCE_LANGUAGE_CODE: Optional[str] = None
    TEMP_DIR: str = "/tmp/notes-bot"

    @cached_property
    def allowed_user_ids(self) -> list[int]:
        return [int(uid.strip()) for uid in self.ALLOWED_USER_IDS.split(",") if uid.strip()]

    @property
    def notion_enabled(self) -> bool:
        return bool(self.NOTION_TOKEN and self.NOTION_DATABASE_ID)

    @property
    def openai_enabled(self) -> bool:
        return bool(self.OPENAI_API_KEY)

    @property
    def assemblyai_enabled(self) -> bool:
        return bool(self.ASSEMBLYAI_API_KEY)

    def database_id_for(self, db_env: str) -> Optional[str]:
        """Resolve per-type DB id by env-name; fall back to default."""
        return getattr(self, db_env, None) or self.NOTION_DATABASE_ID


settings = Settings()
