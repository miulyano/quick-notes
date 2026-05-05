# notes-bot

![version](https://img.shields.io/badge/version-0.1.0-blue)

Telegram-бот для персональных заметок: принимает текст, голос, видео, форварды;
транскрибирует медиа, классифицирует через GPT-4o, сохраняет готовые страницы в
[Notion](https://www.notion.so/).

> Архитектурный план — `~/.claude/plans/notes-bot-giggly-lemur.md`. Эволюция —
> отдельные ветки и Conventional-Commits-PR в `main` (см. `AGENTS.md`).

## Что умеет (на 0.1.0)

Скелет. Принимает текст, отвечает «Получено: …». Никакой бизнес-логики ещё нет
(SQLite, очередь, LLM, Notion подключаются в следующих инкрементах).

## Стек

- Python 3.11
- aiogram 3.x — Telegram bot framework
- pydantic-settings — config через `.env`
- pytest + pytest-asyncio — тесты
- Docker + docker-compose

## Структура проекта

```
bot/
├── main.py                # entry: aiogram polling
├── config.py              # pydantic settings
├── handlers/              # обработчики Telegram update'ов
├── middlewares/
│   └── auth.py            # whitelist Telegram user IDs
├── services/              # бизнес-логика без знания о Telegram
├── domain/                # типы заметок, шаблоны
├── storage/               # SQLite слой (drafts, outbox, idempotency)
├── workers/               # asyncio-таски (outbox-воркер)
├── fsm/                   # FSM-стейты aiogram
└── utils/
    ├── progress.py        # ProgressReporter (статус-сообщение)
    ├── text_chunking.py   # разбиение длинных текстов
    └── errors.py          # UserFacingError
tests/
data/                      # SQLite БД (volume в compose)
```

## Как развернуть свой

### Локально

```bash
python3.11 -m venv .venv
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

## Настройка `.env`

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от `@BotFather` |
| `ALLOWED_USER_IDS` | Разрешённые TG user IDs через запятую |
| `DATABASE_PATH` | Путь к файлу SQLite (по умолчанию `data/notes.db`) |
