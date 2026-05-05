# Changelog

All notable changes to this project follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] – 2026-05-05

### Added
- Скелет проекта: структура `bot/`, конфиг через pydantic-settings, aiogram polling
  с whitelist-middleware и заглушка-обработчик текстовых сообщений.
- Скопированы из `life-transcriber`: `AuthMiddleware`, `ProgressReporter`,
  `text_chunking`, `UserFacingError`.
- Dockerfile + docker-compose.yml (один сервис `bot`, volume `./data`).
- Тесты `test_config.py`, `test_auth.py` через pytest + pytest-asyncio.
