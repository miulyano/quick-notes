# notes-bot

![version](https://img.shields.io/badge/version-0.2.0-blue)

Telegram-бот для персональных заметок: принимает текст, голос, видео, форварды;
транскрибирует медиа, классифицирует через GPT-4o, сохраняет готовые страницы в
[Notion](https://www.notion.so/).

> Архитектурный план — `~/.claude/plans/notes-bot-giggly-lemur.md`. Эволюция —
> отдельные ветки и Conventional-Commits-PR в `main` (см. `AGENTS.md`).

## Что умеет (на 0.2.0)

- Принимает текст в личке.
- Создаёт черновик в SQLite **до** любой обработки (durability-контракт).
- Прогоняет текст через LLM-pipeline (пока stub: тип `note`, title = первая
  строка, тело = исходный текст).
- Показывает превью с inline-кнопками `💾 Save` / `✖️ Cancel`.
- На Save — кладёт в outbox-очередь, фоновой воркер вызывает Notion-клиент
  (пока stub, логирует и возвращает fake `page_id`).
- На успех — атомарно вставляет запись идемпотентности, удаляет черновик и
  outbox-строку. Превью редактируется в «✅ Сохранено в Notion».
- На ошибку — экспоненциальный backoff. После `MAX_ATTEMPTS` черновик помечается
  `failed`, остаётся видимым через `/list`.
- Команды: `/start`, `/help`, `/list` (незавершённые черновики), `/retry`
  (перезапуск всех `failed`).
- На старте: восстановление черновиков, застрявших в `saving` дольше 5 минут.

## Стек

- Python 3.11+
- aiogram 3.x — Telegram bot framework
- pydantic-settings — config через `.env`
- aiosqlite — async-драйвер SQLite
- pytest + pytest-asyncio — тесты
- Docker + docker-compose

## Структура проекта

```
bot/
├── main.py                # entry: init_db → recover_stuck → outbox worker → polling
├── config.py              # pydantic settings
├── handlers/
│   ├── inputs.py          # text → draft → LLM → preview
│   ├── callbacks.py       # Save / Cancel
│   └── commands.py        # /start /help /list /retry
├── middlewares/
│   └── auth.py            # whitelist Telegram user IDs
├── services/
│   ├── llm_processor.py   # stub: classify + format (Increment 3 — реальный GPT-4o)
│   └── notion_client.py   # stub create_page (Increment 2 — реальный notion-client)
├── domain/
│   ├── note_types.py      # пока один тип note
│   └── templates.py       # markdown-шаблоны
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

39 тестов на момент 0.2.0:
- `test_config.py`, `test_auth.py` — конфиг и middleware.
- `test_drafts.py`, `test_outbox.py`, `test_idempotency.py`, `test_save_tx.py` —
  storage-слой (in-memory SQLite через фикстуру `fresh_db`).
- `test_outbox_worker.py` — happy path, retry, idempotency после крэша,
  max_attempts.
- `test_llm_processor.py` — stub.
- `test_handlers_inputs.py`, `test_handlers_callbacks.py` — UX-логика.

## Настройка `.env`

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от `@BotFather` |
| `ALLOWED_USER_IDS` | Разрешённые TG user IDs через запятую |
| `DATABASE_PATH` | Путь к файлу SQLite (по умолчанию `data/notes.db`) |

В следующих инкрементах добавятся `NOTION_TOKEN`, `NOTION_DATABASE_ID`,
`OPENAI_API_KEY`, `ASSEMBLYAI_API_KEY`.
