"""Telegram Web App initData HMAC validation.

Reference: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Алгоритм:
  1. Распарсить query-string из `Telegram.WebApp.initData` (URL-encoded ключи/значения).
  2. Извлечь поле `hash` отдельно (это сама подпись), остальные пары отсортировать
     лексикографически по ключу и склеить как `key=value\\nkey=value\\n...`.
  3. Секрет = HMAC-SHA256("WebAppData", bot_token). Это **не** просто SHA256(token).
  4. Подпись = HMAC-SHA256(secret, data_check_string).hex().
  5. Сравнить через constant-time с пришедшим `hash`.
  6. Опционально проверить `auth_date` на свежесть (Telegram рекомендует 24h max).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl


# Telegram рекомендует считать initData свежей в течение 24h. Поднять/опустить
# через параметр функции при необходимости.
DEFAULT_MAX_AGE_SECS = 24 * 60 * 60


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_secs: int = DEFAULT_MAX_AGE_SECS,
) -> Optional[dict]:
    """Validate Telegram Web App initData. Return parsed dict on success, None otherwise.

    Returned dict содержит все распарсенные поля (auth_date — int, user — dict
    после json.loads, остальные строки). На любой ошибке (битая подпись,
    просрочено, нет user) возвращает None.
    """
    if not init_data or not bot_token:
        return None

    # parse_qsl сохраняет порядок и URL-decoded'ит значения. keep_blank_values=True
    # на всякий случай — Telegram может прислать пустые поля.
    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)

    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    # auth_date freshness
    auth_date_raw = data.get("auth_date")
    if not auth_date_raw:
        return None
    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        return None
    if time.time() - auth_date > max_age_secs:
        return None

    # Распарсить вложенный user (приходит как JSON-string)
    user_raw = data.get("user")
    if user_raw:
        try:
            data["user"] = json.loads(user_raw)
        except (TypeError, ValueError):
            return None
    else:
        return None

    data["auth_date"] = auth_date
    return data
