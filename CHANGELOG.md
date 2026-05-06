# Changelog

All notable changes to this project follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.11.1] – 2026-05-06

### Added
- Раздел «VPS (Ubuntu 22.04 / 24.04)» в README — пошаговая установка
  Docker, деплой, бэкап SQLite, мониторинг через healthchecks.io,
  обновление и troubleshooting.
- `scripts/backup_db.sh` — online-backup SQLite через `sqlite3 .backup`
  + `gzip` + ротация по `KEEP_DAYS` (default 14). Конфиг через env
  vars `APP_DIR`, `BACKUP_DIR`, `KEEP_DAYS`.

### Changed
- `docker-compose.yml`: лимит памяти `220m` → `512m` (для документов
  через map-reduce). Добавлен healthcheck (`SELECT 1` к SQLite, intervals
  60s) и ротация логов (10 МБ × 5 файлов) — `docker logs` больше не
  раздуется на годы работы.

## [0.11.0] – 2026-05-06

### Added
- Хендлер документов (`bot/handlers/documents.py`) — принимает
  `message.document` (форварды и прямой upload) форматов **txt, md, csv,
  pdf, docx**. Текст извлекается локально через новый
  `bot/services/doc_extractor.py` (`pypdf` для PDF, `python-docx` для DOCX,
  stdlib для остальных), затем идёт в существующий LLM-pipeline. Лимит
  размера файла — 20 МБ (Telegram bot API). Аудио/видео, пришедшие как
  document, отбиваются с просьбой переслать как медиа.
- Map-reduce путь в `llm_processor.process_long(...)` для длинных документов
  (>40k символов): сплит на куски, per-chunk summarize-вызов с упором на
  agenda / decisions / action items / status updates / blockers, финальная
  склейка через обычный `process()` для классификации. Прогресс отдаётся
  через `on_fraction` callback в ProgressReporter.

## [0.10.0] – 2026-05-06

### Changed
- `scripts/setup_buildin_dbs`: title страницы-обёртки и full-page DB —
  plural-форма типа без префикса воркспейса (`📝 Заметки`, `✅ Задачи`,
  `💡 Идеи`, `🤝 Митинги`, `👥 1:1`, `💼 Рабочее`, `🌱 Личное`) вместо
  `<ws.label> · <type.label>` (`Работа · ✅ Задача`). Имя space'а уже задаёт
  контекст воркспейса, а в DB лежит много записей одного типа. Старые ресурсы
  не переименовываются — слот пропускается, как и раньше.

## [0.9.0] – 2026-05-06

### Changed
- LLM-обработчик (`services/llm_processor.process`) больше не сваливается
  молча на stub при ошибке OpenAI: пробрасывает `LLMError`. Хендлеры пишут
  `draft.status=failed` и пользователь делает `/retry`. Добавлен timeout 30s
  и встроенный `max_retries=2` у `AsyncOpenAI`.
- Транскрибатор (`services/transcriber._run_assemblyai`) ограничен потолком
  `MAX_POLL_SECONDS=600`. Раньше зависший в processing-статусе AssemblyAI
  крутил ProgressReporter бесконечно. Poll-цикл вытащен в чистую функцию
  `_poll_for_completion` с инжектируемыми clock/sleep — покрыт unit-тестом.
- Миграция `ALTER TABLE drafts ADD COLUMN workspace` в `storage/db.py` теперь
  ловит только `OperationalError("duplicate column name")`. Любая другая
  ошибка (disk full, corruption) срывает старт бота.
- Buildin health-check на старте резолвит database id для каждой пары
  (workspace, type) и логирует fallback к `BUILDIN_DB_DEFAULT` или полное
  отсутствие конфигурации. Раньше опечатка в env-имени проявлялась только
  при первом сохранении.
- Graceful shutdown: ждём завершения outbox worker'а до 35s через
  `asyncio.wait_for`, по таймауту cancel'им. Закрываются httpx-сессии
  OpenAI / Notion / Buildin, чтобы не оставались hanging.

### Refactor
- `_wrap_property` и `build_properties` вынесены из `services/sinks/notion.py`
  и `buildin.py` в общий `services/sinks/_properties.py` с параметром
  `shape="notion"|"buildin"`. Раньше любая правка схемы требовала менять
  два почти-одинаковых блока кода.

### Added
- Тесты: `test_sinks_properties.py` (11 кейсов на оба shape),
  `test_config.test_database_id_*` (7 веток резолва провайдер/workspace/type),
  два теста на `_poll_for_completion` (happy + timeout).

## [0.8.0] – 2026-05-06

### Added
- Подтип `sync` для типа `meeting` — регулярная встреча команды (status check,
  блокеры, назначения). Активируется через `extras.kind="sync"` от LLM.
  Шаблон рендерит секции `## Status updates` / `## Notes` / `## Blockers` /
  `## Action items` (вместо классических agenda/discussion/decisions). Новые
  extras-ключи: `status_updates`, `blockers`. Триггеры в LLM-prompt: «синк»,
  «standup», «daily», «weekly», «status», «команда собралась», «обсудили статусы»,
  «блокеры».
- LLM-prompt теперь явно требует от type=task положить 1-3 параграфа описания
  задачи в `markdown_body` (контекст, мотивация, условия успеха) перед
  `## Чек-лист`. Шаблон уже это поддерживал; промпт довёл до устойчивого поведения.

### Changed
- `scripts/setup_buildin_dbs.py` создаёт DB не в корне space, а на отдельной
  странице-обёртке `<workspace> · <тип>`. Структура в Buildin: space → page
  «✅ Задача» → full-page DB Tasks (и т.п. на каждый тип). Уже существующие
  записи `BUILDIN_DB_<WS>_<TYPE>` в .env скрипт пропускает, поэтому старые DB
  остаются в корне space (смешанная структура допустима; для однородной —
  удалить env-vars и DB вручную, затем перезапустить скрипт).

## [0.7.0] – 2026-05-05

### Added
- Поддержка **Buildin** (https://buildin.ai) как нового sink-провайдера
  заметок (default). Переключатель `NOTES_PROVIDER=buildin|notion` (default
  `buildin`). Старый Notion sink остаётся как fallback, переключается env'ом.
- `bot/services/sinks/` — новый каталог с sink-абстракцией: `Sink` Protocol
  (`__init__.py`), `notion.py` (перенесённый старый клиент, обёрнут в класс
  `NotionSink`), `buildin.py` (новый `BuildinSink` на `httpx`), `factory.py`
  (`get_sink()` по `NOTES_PROVIDER`).
- `bot/domain/workspaces.py` — реестр workspace'ов: `personal` (Личное),
  `work` (Работа), `family` (Семья), `growth` (Куда расти?), `ai_path`
  (Путь ИИ). Default = `personal`.
- LLM classifier (`llm_processor.py`) теперь возвращает поле `workspace`
  (один из ключей реестра); в prompt — секция «Workspaces» с label +
  description каждого. Stub-фолбэк → `personal`.
- UX: новая кнопка `📁 Workspace` в превью + `chws/setws` callbacks.
  Layout превью: верхний ряд `💾 Save | ✖ Cancel`, нижний `🔁 Type | 📁 Workspace`.
  В превью текст показывается с двумя метками: `<тип> · 📁 <workspace>`.
- Buildin sink:
  - bearer auth, base URL `https://api.buildin.ai`;
  - wire-формат: `parent` с `type`-дискриминатором, properties `{type, …}`,
    blocks под ключом `data` (см. `bot/utils/md_blocks.py:markdown_to_blocks_buildin`);
  - **chunking длинных страниц**: после `POST /v1/pages` оставшиеся блоки
    добавляются через `PATCH /v1/blocks/{page_id}/children` чанками по 100;
  - stub-mode при пустом `BUILDIN_TOKEN`.
- Per-(workspace × type) DB routing: `BUILDIN_DB_<WS>_<TYPE>` → fallback
  `BUILDIN_DB_<TYPE>` → `BUILDIN_DB_DEFAULT`. Резолвинг — `settings.database_id_for()`.
- Health-check на старте бота при `NOTES_PROVIDER=buildin`:
  `GET /v1/users/me` (валидация токена) + warn при незаданных
  `BUILDIN_SPACE_<WS>` env'ах.
- `scripts/setup_buildin_dbs.py` — создание недостающих Buildin DB через
  `POST /v1/databases`. Уже привязанные slot'ы (env `BUILDIN_DB_<WS>_<TYPE>`
  задан) не пересоздаются. Поддерживает `--dry-run`, `--workspace`, `--type`.
- `NotionProperty.select_options` — фиксированные опции для select-полей
  (Status: Todo/In Progress/Done; Priority: Low/Medium/High). Используются
  при автосоздании Buildin DB для `PropertySchemaSelect.options`.
- Колонка `workspace` в таблице `drafts` (default `personal`) +
  lightweight миграция `ALTER TABLE drafts ADD COLUMN workspace`.
- `httpx>=0.27` в `requirements.txt` (раньше шёл транзитивно через
  `notion-client`).

### Changed
- `bot/services/notion_client.py` — теперь тонкий compat-shim, ре-экспортирует
  `bot/services/sinks/notion.py`. Старые импорт-пути работают без изменений.
- `bot/utils/md_blocks.py` — общий парсер `parse_markdown(text)` →
  `list[ParsedBlock]`, поверх него обёртки `markdown_to_blocks` (Notion) и
  `markdown_to_blocks_buildin` (Buildin).
- `bot/workers/outbox_worker.py` — использует `get_sink()` вместо прямого
  импорта `notion_client.create_page`.
- В сообщении «✅ Сохранено» — название провайдера выводится по
  `settings.NOTES_PROVIDER`.

## [0.6.0] – 2026-05-05

### Added
- Поддержка форвард-сообщений: текст, голос, аудио, видео, видео-кружочки.
- `bot/utils/forward.py`: `extract(message)` парсит `forward_origin`
  (User / HiddenUser / Chat / Channel) → метаданные (автор, канал, дата,
  подпись, оригинальный message_id). `format_prefix(meta)` рендерит
  компактный context-блок `[Forwarded] От: …; Когда: …`.
- В `handlers/inputs.py` и `handlers/voice.py`: при наличии `forward_origin`
  draft создаётся как `kind=forward`, `raw_payload` хранит JSON с текстом и
  метаданными, в LLM подаётся **enriched-text** с prefix'ом — классификатор
  получает контекст «это форвард, а не моя мысль».
- 9 новых тестов forward (User/HiddenUser/Chat/Channel/no-forward/format_prefix/
  enrich) + интеграционный тест в `test_handlers_inputs.py` (kind=forward,
  enriched LLM-input). Всего 97 — все зелёные.

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
