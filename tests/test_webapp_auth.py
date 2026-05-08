"""Юнит-тесты для bot/web/auth.validate_init_data."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from bot.web.auth import validate_init_data


BOT_TOKEN = "1234567890:fake-bot-token-for-tests"


def _sign(fields: dict, *, token: str = BOT_TOKEN) -> str:
    """Помощник: построить корректный Telegram Web App initData по схеме docs."""
    pairs = sorted(fields.items())
    data_check_string = "\n".join(f"{k}={v}" for k, v in pairs)
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    encoded = urlencode(pairs)
    return f"{encoded}&hash={digest}"


def _fields(*, auth_date: int | None = None, user_id: int = 111) -> dict:
    return {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAFakeQueryId",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test", "username": "test"},
            separators=(",", ":"),
        ),
    }


def test_valid_signature_returns_user():
    init = _sign(_fields(user_id=123))
    result = validate_init_data(init, BOT_TOKEN)
    assert result is not None
    assert result["user"]["id"] == 123
    assert isinstance(result["auth_date"], int)


def test_tampered_hash_returns_none():
    init = _sign(_fields())
    # Заменим последний hex-символ — подпись сломана.
    tampered = init[:-1] + ("0" if init[-1] != "0" else "1")
    assert validate_init_data(tampered, BOT_TOKEN) is None


def test_tampered_user_returns_none():
    init = _sign(_fields(user_id=111))
    # Подменим часть данных (id в URL-encoded user-поле) — подпись не сходится.
    # urlencode превращает {"id":111,...} в %7B%22id%22%3A111... — целевой паттерн.
    tampered = init.replace("%3A111%2C", "%3A999%2C")
    assert tampered != init  # sanity: подмена реально произошла
    assert validate_init_data(tampered, BOT_TOKEN) is None


def test_wrong_token_returns_none():
    init = _sign(_fields())
    assert validate_init_data(init, "different-token") is None


def test_stale_auth_date_returns_none():
    # auth_date старше 24 часов
    old = int(time.time()) - 25 * 60 * 60
    init = _sign(_fields(auth_date=old))
    assert validate_init_data(init, BOT_TOKEN) is None


def test_custom_max_age_allows_old_data():
    old = int(time.time()) - 25 * 60 * 60
    init = _sign(_fields(auth_date=old))
    result = validate_init_data(init, BOT_TOKEN, max_age_secs=48 * 60 * 60)
    assert result is not None


def test_missing_hash_returns_none():
    encoded = urlencode([("auth_date", str(int(time.time()))), ("user", "{}")])
    assert validate_init_data(encoded, BOT_TOKEN) is None


def test_missing_user_returns_none():
    fields = {"auth_date": str(int(time.time())), "query_id": "X"}
    init = _sign(fields)
    assert validate_init_data(init, BOT_TOKEN) is None


def test_empty_init_data_returns_none():
    assert validate_init_data("", BOT_TOKEN) is None


def test_empty_token_returns_none():
    init = _sign(_fields())
    assert validate_init_data(init, "") is None
