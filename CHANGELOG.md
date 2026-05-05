# Changelog

All notable changes to this project follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
