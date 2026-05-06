# notes-bot

![version](https://img.shields.io/badge/version-0.8.0-blue)

Telegram-бот для персональных заметок: принимает текст, голос, видео, форварды;
транскрибирует медиа, классифицирует через GPT-4o, сохраняет готовые страницы в
[Buildin](https://buildin.ai) (по умолчанию) или [Notion](https://www.notion.so/) —
переключатель `NOTES_PROVIDER=buildin|notion`.

> Архитектурный план — `~/.claude/plans/notes-bot-giggly-lemur.md`. Эволюция —
> отдельные ветки и Conventional-Commits-PR в `main` (см. `AGENTS.md`).

## Что умеет (на 0.8.0)

- Принимает **текст, голосовые, аудио, видео, видео-кружочки, форварды**.
- Голос/аудио/видео транскрибируется через **AssemblyAI Universal-2** с
  диаризацией спикеров. Сырой транскрипт остаётся в БД (промежуточный шаг),
  в провайдер уходит только готовая заметка после LLM. Без
  `ASSEMBLYAI_API_KEY` — голосовые отключены, бот отвечает «транскрибация
  выключена».
- Для форвардов извлекаются метаданные (автор, канал, дата, подпись,
  оригинальный message_id) и подаются в LLM как контекст-prefix
  `[Forwarded] От: …; Когда: …`. Draft помечается `kind=forward`.
- Создаёт черновик в SQLite **до** любой обработки (durability-контракт).
- **Один GPT-4o-вызов**: классифицирует тип (note / task / idea / meeting /
  1on1 / work / personal), **выбирает workspace** (personal / work / family /
  growth / ai_path), извлекает properties (Status, Priority, DueDate, Tags,
  Attendees, …) и форматирует тело как markdown под template типа. Для
  `meeting` отдельно различает регулярные синки команды через
  `extras.kind="sync"` — рендер ставит секции Status updates / Blockers /
  Action items вместо классических Agenda / Decisions. Для `task`
  описание задачи (контекст, мотивация) пишется в `markdown_body` перед
  `## Чек-лист`. Без `OPENAI_API_KEY` — stub-fallback (тип `note`, workspace
  `personal`, тело = исходник).
- Превью с кнопками: `💾 Save` / `✖ Cancel` сверху, `🔁 Type` /
  `📁 Workspace` снизу. Workspace и тип можно переопределить вручную.
- На Save — кладёт в outbox-очередь, фоновой воркер вызывает API провайдера
  (Buildin или Notion в зависимости от `NOTES_PROVIDER`).
- **Routing**: per-(workspace × type) для Buildin (`BUILDIN_DB_<WS>_<TYPE>`)
  с фолбэком на per-type / default; per-type для Notion (`NOTION_DB_<TYPE>`)
  с фолбэком на `NOTION_DATABASE_ID`. Без токена провайдера — stub-режим.
- Markdown тела заметки конвертируется в provider-specific blocks (параграфы,
  заголовки `#`/`##`/`###`, списки `-`/`1.`, цитаты `>`, code-fences ` ``` `).
  Для Buildin длинные заметки (>100 блоков) дописываются чанками по 100
  через `PATCH /v1/blocks/{page_id}/children`.
- На успех — атомарно `idempotency.insert + drafts.delete + outbox.delete`.
  Превью редактируется в «✅ Сохранено в Buildin/Notion».
- На ошибку — экспоненциальный backoff. После `MAX_ATTEMPTS` черновик
  помечается `failed`, остаётся видимым через `/list`.
- При `NOTES_PROVIDER=buildin` бот на старте делает health-check
  (`GET /v1/users/me`) и предупреждает о незаданных
  `BUILDIN_SPACE_<WS>` env'ах.
- Команды: `/start`, `/help`, `/list`, `/retry`.
- На старте: восстановление черновиков, застрявших в `saving` дольше 5 минут.

## Подключение Buildin (default)

### 1. Integration

В Buildin: settings → integrations → создать новую integration. Скопировать
токен → `BUILDIN_TOKEN` в `.env`.

### 2. Spaces (workspace'ы)

Бот поддерживает 5 workspace'ов: `personal`, `work`, `family`, `growth`,
`ai_path`. Для каждого нужен отдельный Buildin space. Создайте space'ы
руками, разрешите для них integration, скопируйте UUID:

| Workspace | Env var |
|---|---|
| `personal` (Личное) | `BUILDIN_SPACE_PERSONAL` |
| `work` (Работа) | `BUILDIN_SPACE_WORK` |
| `family` (Семья) | `BUILDIN_SPACE_FAMILY` |
| `growth` (Куда расти?) | `BUILDIN_SPACE_GROWTH` |
| `ai_path` (Путь ИИ) | `BUILDIN_SPACE_AI_PATH` |

### 3. Базы (databases)

Внутри каждого space скрипт создаёт отдельную **страницу-обёртку** на каждый
тип заметки (`<ws.label> · <type.label>`, например «Работа · ✅ Задача»),
а внутри страницы — full-page DB этого типа. Структура в Buildin:

```
space «Работа»
├── page «Работа · ✅ Задача»
│   └── DB Tasks
├── page «Работа · 📝 Заметка»
│   └── DB Notes
└── …
```

Можно создать руками (тогда скопируйте UUID DB из URL в `BUILDIN_DB_<WS>_<TYPE>`),
либо запустить автосоздание:

```bash
source .venv/bin/activate
python -m scripts.setup_buildin_dbs >> .env
```

Скрипт уважает уже заданные env'ы — заполняет только пустые slot'ы.
Доп. флаги: `--dry-run` (без сетевых вызовов), `--workspace=<key>`,
`--type=<key>` (только конкретный workspace или тип).

Если у вас остались DB, созданные старой версией скрипта (лежат прямо в
корне space, без page-обёртки), они продолжат работать — env-vars у них
уже заполнены, скрипт их пропускает. Чтобы получить однородную структуру,
удалите соответствующие `BUILDIN_DB_<WS>_<TYPE>` из `.env`, удалите DB в
Buildin UI и перезапустите скрипт.

Кроме перечисленных свойств бот всегда дописывает `CreatedAt` (date) — оно
создаётся скриптом автоматически.

### 4. Переключатель провайдера

`NOTES_PROVIDER=buildin` (default) включает Buildin sink. Для возврата на
Notion поставьте `NOTES_PROVIDER=notion`.

## Подключение Notion

### 1. Интеграция

Создать **Internal Integration** на https://www.notion.so/my-integrations,
скопировать токен → `NOTION_TOKEN` в `.env`.

### 2. Базы под каждый тип

Под каждый тип заметок создаётся **отдельная Notion-база** со своей схемой и
шарится с интеграцией. Тип, для которого `NOTION_DB_<TYPE>` пуст, попадает
в базу из `NOTION_DATABASE_ID` (fallback).

| Тип | Env var | Required properties (имя — kind) |
|---|---|---|
| `note` | `NOTION_DB_NOTE` | Name (title), Tags (multi_select) |
| `task` | `NOTION_DB_TASK` | Name (title), Status (select), Priority (select), DueDate (date) |
| `idea` | `NOTION_DB_IDEA` | Name (title), Tags (multi_select) |
| `meeting` | `NOTION_DB_MEETING` | Name (title), Attendees (multi_select), Date (date) |
| `1on1` | `NOTION_DB_1ON1` | Name (title), With (rich_text), Date (date) |
| `work` | `NOTION_DB_WORK` | Name (title), Tags (multi_select) |
| `personal` | `NOTION_DB_PERSONAL` | Name (title), Tags (multi_select) |

Кроме перечисленных — бот всегда дописывает `CreatedAt` (date). Это поле
должно присутствовать в каждой базе.

### 3. Шаринг

Для каждой базы: `…` (меню в правом верхнем углу) → **Connections** →
выбрать интеграцию.

### 4. ID

Скопировать database id из URL (32-символьный hex после workspace) в
соответствующую переменную `.env`. Без `NOTION_TOKEN`/`NOTION_DATABASE_ID`
бот работает в stub-режиме (логирует payload).

## OpenAI

`OPENAI_API_KEY` в `.env` — включает реальный GPT-4o. Без ключа — stub
(тип `note`, body = raw input). Модель меняется через `OPENAI_MODEL`
(по умолчанию `gpt-4o`).

## Стек

- Python 3.11+
- aiogram 3.x — Telegram bot framework
- pydantic-settings — config через `.env`
- aiosqlite — async-драйвер SQLite
- httpx — async HTTP-клиент для Buildin API (тонкий клиент по openapi)
- notion-client — Python SDK Notion API (legacy fallback провайдер)
- openai — GPT-4o classify+format одним вызовом
- assemblyai — Universal-2 транскрибация + диаризация
- pytest + pytest-asyncio — тесты
- Docker + docker-compose

## Структура проекта

```
bot/
├── main.py                # entry: init_db → recover_stuck → outbox worker → polling
├── config.py              # pydantic settings
├── handlers/
│   ├── inputs.py          # text → draft → LLM → preview
│   ├── voice.py           # voice/audio/video/video_note → download → transcribe → LLM → preview
│   ├── callbacks.py       # Save / Type / Cancel + клавиатура выбора типа
│   └── commands.py        # /start /help /list /retry
├── middlewares/
│   └── auth.py            # whitelist Telegram user IDs
├── services/
│   ├── llm_processor.py   # GPT-4o classify+format (один вызов) + stub fallback
│   ├── notion_client.py   # compat-shim → sinks/notion.py
│   ├── transcriber.py     # AssemblyAI Universal-2 + диаризация (multi-speaker labels)
│   └── sinks/             # провайдеры хранилища заметок
│       ├── __init__.py    # Sink Protocol
│       ├── notion.py      # NotionSink — pages.create через notion-client
│       ├── buildin.py     # BuildinSink — httpx + Buildin API (default)
│       └── factory.py     # get_sink() по NOTES_PROVIDER
├── domain/
│   ├── note_types.py      # 7 типов с properties + db_env + LLM-hints + select_options
│   ├── workspaces.py      # реестр workspaces (personal/work/family/growth/ai_path)
│   └── templates.py       # per-type markdown шаблоны
├── storage/
│   ├── db.py              # aiosqlite-соединение, WAL, миграции
│   ├── drafts.py          # CRUD черновиков
│   ├── outbox.py          # очередь с экспоненциальным backoff
│   ├── idempotency.py     # dedup draft_id → page_id
│   └── save_tx.py         # атомарный commit_save
├── workers/
│   └── outbox_worker.py   # asyncio task: claim_due → save → commit
├── fsm/                   # FSM-стейты (пока пусто, нужен в Increment 3)
└── utils/
    ├── progress.py        # ProgressReporter
    ├── text_chunking.py
    ├── md_blocks.py       # parse_markdown + markdown_to_blocks (Notion) + markdown_to_blocks_buildin
    ├── forward.py         # извлечение метаданных forward + prefix для LLM
    └── errors.py
scripts/
└── setup_buildin_dbs.py   # авто-создание Buildin DB по реестрам
tests/                     # pytest + pytest-asyncio, in-memory SQLite фикстура
data/                      # SQLite БД (volume в compose)
```

## Как развернуть свой

### Локально

```bash
python3.12 -m venv .venv  # python3.11+ тоже подходит
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# заполнить BOT_TOKEN и ALLOWED_USER_IDS

python -m bot.main
```

### Docker

```bash
cp .env.example .env
docker compose up --build
```

## Тесты

```bash
source .venv/bin/activate
pytest -v
```

133+ тестов на момент 0.8.0:
- `test_config.py`, `test_auth.py` — конфиг и middleware.
- `test_drafts.py`, `test_outbox.py`, `test_idempotency.py`, `test_save_tx.py` —
  storage-слой (in-memory SQLite через фикстуру `fresh_db`).
- `test_outbox_worker.py` — happy path, retry, idempotency после крэша,
  max_attempts.
- `test_note_types.py`, `test_templates.py`, `test_workspaces.py` — реестры.
- `test_llm_processor.py` — stub + real path с моком OpenAI (включая
  workspace classification + fallback на ошибке и неизвестный тип/workspace).
- `test_handlers_inputs.py`, `test_handlers_callbacks.py` — UX-логика
  (выбор типа + workspace).
- `test_md_blocks.py`, `test_md_blocks_buildin.py` — markdown → blocks для
  Notion и Buildin shapes.
- `test_notion_client.py` — Notion sink: stub/real mode, per-type DB routing,
  multi_select, fallback title, failure-injector.
- `test_buildin_sink.py` — Buildin sink (httpx MockTransport): wire shape,
  workspace × type routing, chunking длинных заметок, error mapping,
  health-check `/v1/users/me`.
- `test_workspace_routing.py` — `settings.database_id_for()` для обоих
  провайдеров.
- `test_sink_factory.py` — `get_sink()` переключение по `NOTES_PROVIDER`.
- `test_transcriber.py` — диаризация render-with-speakers, disabled-flag.
- `test_handlers_voice.py` — happy path с моками download/transcribe/LLM,
  durability при ошибках.
- `test_forward.py` — извлечение метаданных всех типов forward_origin
  (User/HiddenUser/Chat/Channel) + format_prefix + enrich.

## Настройка `.env`

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от `@BotFather` |
| `ALLOWED_USER_IDS` | Разрешённые TG user IDs через запятую |
| `DATABASE_PATH` | Путь к файлу SQLite (по умолчанию `data/notes.db`) |
| `NOTES_PROVIDER` | `buildin` (default) или `notion` |
| `BUILDIN_TOKEN` | Токен Buildin integration. Пусто → stub-режим |
| `BUILDIN_SPACE_<WS>` | UUID space'а workspace'а (`PERSONAL`, `WORK`, `FAMILY`, `GROWTH`, `AI_PATH`). Нужны для setup-script |
| `BUILDIN_DB_<WS>_<TYPE>` | Per-(workspace × type) DB id. Заполняется setup-script'ом или руками |
| `BUILDIN_DB_<TYPE>` | Per-type fallback DB id (без workspace-разреза) |
| `BUILDIN_DB_DEFAULT` | Финальный fallback DB id |
| `NOTION_TOKEN` | Токен Internal Integration Notion. Пусто → stub-режим |
| `NOTION_DATABASE_ID` | Default DB id (fallback для типов без своей переменной) |
| `NOTION_DB_<TYPE>` | Per-type DB id: `NOTE`, `TASK`, `IDEA`, `MEETING`, `1ON1`, `WORK`, `PERSONAL`. Все optional |
| `OPENAI_API_KEY` | Ключ OpenAI для GPT-4o classify+format. Пусто → stub |
| `OPENAI_MODEL` | Имя модели (по умолчанию `gpt-4o`) |
| `ASSEMBLYAI_API_KEY` | Ключ AssemblyAI для транскрибации. Пусто → voice/audio/video отключены |
| `ASSEMBLYAI_SPEECH_MODEL` | `universal` (default), `nano` или `slam-1` |
| `FORCE_LANGUAGE_CODE` | `ru`, `en`, …  Пусто → autodetect (ненадёжно для <30 сек) |
| `TEMP_DIR` | Временные файлы для скачанных медиа (по умолчанию `/tmp/notes-bot`) |
