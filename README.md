# notes-bot

![version](https://img.shields.io/badge/version-0.5.0-blue)

Telegram-бот для персональных заметок: принимает текст, голос, видео, форварды;
транскрибирует медиа, классифицирует через GPT-4o, сохраняет готовые страницы в
[Notion](https://www.notion.so/).

> Архитектурный план — `~/.claude/plans/notes-bot-giggly-lemur.md`. Эволюция —
> отдельные ветки и Conventional-Commits-PR в `main` (см. `AGENTS.md`).

## Что умеет (на 0.5.0)

- Принимает **текст, голосовые, аудио, видео, видео-кружочки**.
- Голос/аудио/видео транскрибируется через **AssemblyAI Universal-2** с
  диаризацией спикеров. Сырой транскрипт остаётся в БД (промежуточный шаг),
  в Notion идёт только готовая заметка после LLM. Без `ASSEMBLYAI_API_KEY` —
  голосовые отключены, бот отвечает «транскрибация выключена».
- Создаёт черновик в SQLite **до** любой обработки (durability-контракт).
- **Один GPT-4o-вызов**: классифицирует тип (note / task / idea / meeting /
  1on1 / work / personal), извлекает properties (Status, Priority, DueDate,
  Tags, Attendees, …) и форматирует тело как markdown под template типа.
  Без `OPENAI_API_KEY` — stub-fallback (тип `note`, тело = исходник).
- Показывает превью с тремя кнопками: `💾 Save` / `🔁 Type` (поменять тип
  через клавиатуру со всеми категориями) / `✖️ Cancel`.
- На Save — кладёт в outbox-очередь, фоновой воркер вызывает Notion API.
- Per-type Notion DB routing: каждый тип попадает в свою базу по
  `NOTION_DB_<TYPE>`. Если переменная не задана — fallback на
  `NOTION_DATABASE_ID`. Без `NOTION_TOKEN` — stub-режим.
- Markdown тела заметки конвертируется в Notion blocks (параграфы,
  заголовки `#`/`##`/`###`, списки `-`/`1.`, цитаты `>`, code-fences ` ``` `).
- На успех — атомарно `idempotency.insert + drafts.delete + outbox.delete`.
  Превью редактируется в «✅ Сохранено в Notion».
- На ошибку — экспоненциальный backoff. После `MAX_ATTEMPTS` черновик
  помечается `failed`, остаётся видимым через `/list`.
- Команды: `/start`, `/help`, `/list`, `/retry`.
- На старте: восстановление черновиков, застрявших в `saving` дольше 5 минут.

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
- notion-client — Python SDK Notion API
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
│   ├── notion_client.py   # реальный pages.create через notion-client + per-type DB routing
│   └── transcriber.py     # AssemblyAI Universal-2 + диаризация (multi-speaker labels)
├── domain/
│   ├── note_types.py      # 7 типов с properties + db_env + LLM-hints
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
    ├── md_blocks.py       # markdown → Notion blocks
    └── errors.py
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

87 тестов на момент 0.5.0:
- `test_config.py`, `test_auth.py` — конфиг и middleware.
- `test_drafts.py`, `test_outbox.py`, `test_idempotency.py`, `test_save_tx.py` —
  storage-слой (in-memory SQLite через фикстуру `fresh_db`).
- `test_outbox_worker.py` — happy path, retry, idempotency после крэша,
  max_attempts.
- `test_note_types.py`, `test_templates.py` — реестр типов и шаблоны.
- `test_llm_processor.py` — stub + real path с моком OpenAI (включая
  fallback на ошибке и неизвестный тип).
- `test_handlers_inputs.py`, `test_handlers_callbacks.py` — UX-логика
  включая выбор типа.
- `test_md_blocks.py` — конвертер markdown → Notion blocks.
- `test_notion_client.py` — stub/real mode, per-type DB routing,
  multi_select, fallback title, failure-injector.
- `test_transcriber.py` — диаризация render-with-speakers, disabled-flag.
- `test_handlers_voice.py` — happy path с моками download/transcribe/LLM,
  durability при ошибках.

## Настройка `.env`

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от `@BotFather` |
| `ALLOWED_USER_IDS` | Разрешённые TG user IDs через запятую |
| `DATABASE_PATH` | Путь к файлу SQLite (по умолчанию `data/notes.db`) |
| `NOTION_TOKEN` | Токен Internal Integration Notion. Пусто → stub-режим |
| `NOTION_DATABASE_ID` | Default DB id (fallback для типов без своей переменной) |
| `NOTION_DB_<TYPE>` | Per-type DB id: `NOTE`, `TASK`, `IDEA`, `MEETING`, `1ON1`, `WORK`, `PERSONAL`. Все optional |
| `OPENAI_API_KEY` | Ключ OpenAI для GPT-4o classify+format. Пусто → stub |
| `OPENAI_MODEL` | Имя модели (по умолчанию `gpt-4o`) |
| `ASSEMBLYAI_API_KEY` | Ключ AssemblyAI для транскрибации. Пусто → voice/audio/video отключены |
| `ASSEMBLYAI_SPEECH_MODEL` | `universal` (default), `nano` или `slam-1` |
| `FORCE_LANGUAGE_CODE` | `ru`, `en`, …  Пусто → autodetect (ненадёжно для <30 сек) |
| `TEMP_DIR` | Временные файлы для скачанных медиа (по умолчанию `/tmp/notes-bot`) |
