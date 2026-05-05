import os
from functools import cached_property
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    BOT_TOKEN: str
    ALLOWED_USER_IDS: str  # comma-separated list, parsed via property
    DATABASE_PATH: str = "data/notes.db"

    # Куда сохранять заметки. По умолчанию — Buildin (новый дефолт).
    NOTES_PROVIDER: Literal["buildin", "notion"] = "buildin"

    # Notion integration. NOTION_TOKEN + NOTION_DATABASE_ID (default fallback DB)
    # both required to enable real saves. Per-type DB overrides below — если
    # тип-DB var пустой, используется default DB.
    NOTION_TOKEN: Optional[str] = None
    NOTION_DATABASE_ID: Optional[str] = None
    NOTION_DB_NOTE: Optional[str] = None
    NOTION_DB_TASK: Optional[str] = None
    NOTION_DB_IDEA: Optional[str] = None
    NOTION_DB_MEETING: Optional[str] = None
    NOTION_DB_1ON1: Optional[str] = None
    NOTION_DB_WORK: Optional[str] = None
    NOTION_DB_PERSONAL: Optional[str] = None

    # Buildin integration. BUILDIN_TOKEN + хотя бы один BUILDIN_DB_* — enable real saves.
    # Spaces (BUILDIN_SPACE_<WS>) нужны только для скрипта setup_buildin_dbs.
    # DB IDs хранятся как BUILDIN_DB_<WS>_<TYPE> и читаются через
    # database_id_for() напрямую из os.environ — pydantic игнорирует их (extra=ignore).
    BUILDIN_TOKEN: Optional[str] = None
    BUILDIN_DB_DEFAULT: Optional[str] = None

    # OpenAI for classify+format. Empty → llm_processor stub (single 'note' type,
    # body == raw input). Полезно для dev без расходов на API.
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
    def buildin_enabled(self) -> bool:
        return bool(self.BUILDIN_TOKEN)

    @property
    def openai_enabled(self) -> bool:
        return bool(self.OPENAI_API_KEY)

    @property
    def assemblyai_enabled(self) -> bool:
        return bool(self.ASSEMBLYAI_API_KEY)

    def database_id_for(
        self,
        note_type_db_env: str,
        *,
        provider: Optional[str] = None,
        workspace_key: Optional[str] = None,
    ) -> Optional[str]:
        """Резолвинг DB id для (provider, workspace, type).

        provider:
          - None → используется текущий NOTES_PROVIDER.
          - "notion" → старая логика: per-type env (NOTION_DB_<TYPE>) → fallback NOTION_DATABASE_ID.
          - "buildin" → BUILDIN_DB_<WS>_<TYPE> → BUILDIN_DB_<TYPE> → BUILDIN_DB_DEFAULT.

        note_type_db_env передаётся как имя env-переменной типа (например
        "NOTION_DB_TASK"). Для Buildin отрезаем префикс и берём суффикс типа.
        """
        provider = provider or self.NOTES_PROVIDER
        if provider == "notion":
            return getattr(self, note_type_db_env, None) or self.NOTION_DATABASE_ID

        # Buildin: соответствие имени env по типу: NOTION_DB_TASK → BUILDIN_DB_<WS>_TASK.
        type_suffix = note_type_db_env.removeprefix("NOTION_DB_")
        if workspace_key:
            ws_env = f"BUILDIN_DB_{workspace_key.upper()}_{type_suffix}"
            ws_value = os.environ.get(ws_env)
            if ws_value:
                return ws_value
        type_only_env = f"BUILDIN_DB_{type_suffix}"
        return os.environ.get(type_only_env) or self.BUILDIN_DB_DEFAULT

    def buildin_space_id(self, workspace_key: str) -> Optional[str]:
        return os.environ.get(f"BUILDIN_SPACE_{workspace_key.upper()}")


settings = Settings()
