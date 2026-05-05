# Changelog

All notable changes to this project follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.0] – 2026-05-05

### Added
- Голос/аудио/видео/видео-кружочки: `bot/handlers/voice.py` — единый
  handler через `F.voice | F.audio | F.video | F.video_note`. Pipeline:
  draft (status=raw, file_id в payload) → download → AssemblyAI Universal-2 →
  draft.transcribed → LLM classify+format → preview с теми же кнопками
  Save/Type/Cancel. Сырой транскрипт остаётся в БД, в Notion идёт только
  готовая заметка после LLM.
- `bot/services/transcriber.py`: упрощённая обёртка над `assemblyai` SDK с
  диаризацией. Multi-speaker → строки `A: ...` / `B: ...` для LLM.
  `set_client_override()` test hook. Без `ASSEMBLYAI_API_KEY` —
  RuntimeError, handler отвечает «транскрибация выключена».
- ProgressReporter подключён к статусу: «Скачиваю…» → «Транскрибирую…» →
  «Готовлю заметку…».
- Sweep `TEMP_DIR` создаётся на старте бота. Volume в compose
  (`./tmp:/tmp/notes-bot`).
- Durability при сбоях медиа: download fail → draft в `status=raw` с
  `file_id` (видно через `/list`). Transcribe fail — то же.
- 9 новых тестов: `test_transcriber.py` (render-with-speakers, disabled
  raises), `test_handlers_voice.py` (happy path с моками, durability
  при ошибках download/transcribe). Всего 87 — все зелёные.

### Changed
- `requirements.txt`: добавлен `assemblyai>=0.35`.
- `bot/config.py`: `ASSEMBLYAI_API_KEY`, `ASSEMBLYAI_SPEECH_MODEL`,
  `FORCE_LANGUAGE_CODE`, `TEMP_DIR`, свойство `assemblyai_enabled`.
- `bot/main.py`: подключён voice router, `os.makedirs(TEMP_DIR)` на старте.

## [0.4.0] – 2026-05-05

### Added
- Реальный GPT-4o classify+format одним вызовом (`services/llm_processor.py`).
  Без `OPENAI_API_KEY` — fallback в stub. На ошибку OpenAI — тоже stub.
- `domain/note_types.py`: 7 типов заметок (`note`, `task`, `idea`, `meeting`,
  `1on1`, `work`, `personal`). Каждый со своим описанием для LLM, набором
  properties (Notion-mapping) и `db_env`-переменной.
- `domain/templates.py`: per-type markdown-шаблоны (task/meeting/1on1
  получают структурированное оформление из `extras`, остальные — passthrough).
- Per-type Notion DB routing: `NOTION_DB_TASK`, `NOTION_DB_IDEA`,
  `NOTION_DB_MEETING`, `NOTION_DB_1ON1`, `NOTION_DB_WORK`, `NOTION_DB_PERSONAL`,
  `NOTION_DB_NOTE`. Если для типа DB не задан — fallback на `NOTION_DATABASE_ID`.
- `notion_client.build_properties()`: преобразование `draft.properties` (JSON
  от LLM) в Notion-properties payload по типу (title/rich_text/select/
  multi_select/date/checkbox).
- Кнопка `🔁 Type` в превью + полная клавиатура выбора типа с возвратом
  через `⬅️ Назад`. После смены — превью перерисовывается с новым label.
- 24 новых теста: `test_note_types.py` (6), `test_templates.py` (8),
  обновлён `test_llm_processor.py` (5 real-path), `test_notion_client.py`
  (per-type DB, multi-select, fallback). Всего 78 — все зелёные.

### Changed
- `requirements.txt`: добавлен `openai>=1.50`.
- `bot/config.py`: per-type DB env vars + `OPENAI_API_KEY` + `OPENAI_MODEL`,
  свойство `openai_enabled`, метод `database_id_for(db_env)`.
- `services/llm_processor.py`: расширил `ProcessedNote` полем `extras`,
  добавил `set_client()` test hook, system prompt с описанием всех типов.
- `services/notion_client.py`: routing по `note_type.db_env`, properties
  строятся через `build_properties()` из конфига типа.

## [0.3.0] – 2026-05-05

### Added
- Реальная интеграция с Notion: `services/notion_client.py` теперь делает
  `pages.create` через `notion-client` SDK когда заданы `NOTION_TOKEN` +
  `NOTION_DATABASE_ID`. Без них — fallback в stub-режим (логирует payload).
- `bot/utils/md_blocks.py`: конвертер markdown → Notion blocks
  (paragraphs, headings 1-3, bullet/numbered lists, quote, code fences).
  Длинные абзацы автоматически разбиваются по `MAX_RICH_TEXT_LEN=2000`.
- Notion-database schema documented в `.env.example` и README:
  required properties `Name` (title), `Type` (select), `CreatedAt` (date).
- `set_client()` test hook в `notion_client.py` для подмены SDK в тестах.
- 15 новых тестов (md_blocks + notion_client real/stub/failure-injector),
  всего 54 — все зелёные.

### Changed
- `requirements.txt`: добавлен `notion-client>=2.2`.
- `bot/config.py`: `NOTION_TOKEN`, `NOTION_DATABASE_ID` (Optional) +
  свойство `notion_enabled`.

## [0.2.0] – 2026-05-05

### Added
- SQLite-слой (`bot/storage/`): `db.py` (WAL, миграции), `drafts.py`,
  `outbox.py` (экспоненциальный backoff), `idempotency.py`, `save_tx.py`
  (атомарная транзакция `idempotency.insert + drafts.delete + outbox.delete`).
- Outbox-воркер (`bot/workers/outbox_worker.py`) с поддержкой ретраев,
  идемпотентности после крэша и `MAX_ATTEMPTS` → `status=failed`.
- Stub-сервисы: `services/llm_processor.py` (тип `note`, title из первой
  строки), `services/notion_client.py` (логирует и возвращает fake `page_id`,
  есть failure-injector для тестов).
- Handlers: `inputs.py` (текст → draft до обработки → LLM → превью с
  кнопками Save/Cancel), `callbacks.py`, `commands.py` (`/start`, `/help`,
  `/list`, `/retry`).
- `main.py`: инициализация БД, восстановление stuck-черновиков на старте,
  фоновой outbox-воркер, ack-callbacks через редактирование превью.
- 29 новых тестов (drafts, outbox, idempotency, save_tx, llm, handlers,
  outbox_worker), всего 39 — все зелёные.

### Changed
- `requirements.txt`: добавлен `aiosqlite>=0.19`.

## [0.1.0] – 2026-05-05

### Added
- Скелет проекта: структура `bot/`, конфиг через pydantic-settings, aiogram polling
  с whitelist-middleware и заглушка-обработчик текстовых сообщений.
- Скопированы из `life-transcriber`: `AuthMiddleware`, `ProgressReporter`,
  `text_chunking`, `UserFacingError`.
- Dockerfile + docker-compose.yml (один сервис `bot`, volume `./data`).
- Тесты `test_config.py`, `test_auth.py` через pytest + pytest-asyncio.
