"""TMDb enrich_film: httpx MockTransport, без реальной сети.

Проверяем три ветки:
- TMDB_API_KEY не задан → None.
- Удачный поиск → возвращает {director, year, genres}.
- Пустые results на ru-RU → fallback в en-US.
- API возвращает 5xx / network error → None (graceful).
"""

from __future__ import annotations

import httpx
import pytest

from bot.services import tmdb


@pytest.fixture(autouse=True)
def _reset_state():
    tmdb.set_client(None)
    yield
    tmdb.set_client(None)


async def test_no_api_key_returns_none(monkeypatch):
    monkeypatch.setattr("bot.services.tmdb.settings.TMDB_API_KEY", None)
    result = await tmdb.enrich_film("Interstellar")
    assert result is None


async def test_empty_title_returns_none(monkeypatch):
    monkeypatch.setattr("bot.services.tmdb.settings.TMDB_API_KEY", "k")
    result = await tmdb.enrich_film("  ")
    assert result is None


async def test_successful_lookup(monkeypatch):
    monkeypatch.setattr("bot.services.tmdb.settings.TMDB_API_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        if "/search/movie" in request.url.path:
            return httpx.Response(
                200,
                json={"results": [{"id": 157336, "title": "Интерстеллар"}]},
            )
        if "/movie/157336" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "release_date": "2014-11-05",
                    "genres": [
                        {"id": 12, "name": "Приключения"},
                        {"id": 18, "name": "Драма"},
                    ],
                    "production_countries": [
                        {"iso_3166_1": "US", "name": "United States of America"},
                        {"iso_3166_1": "GB", "name": "United Kingdom"},
                    ],
                    "credits": {
                        "crew": [
                            {"job": "Director", "name": "Christopher Nolan"},
                            {"job": "Writer", "name": "Jonathan Nolan"},
                        ]
                    },
                },
            )
        return httpx.Response(404)

    tmdb.set_client(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    result = await tmdb.enrich_film("Interstellar")
    assert result == {
        "director": "Christopher Nolan",
        "year": "2014",
        "genres": ["Приключения", "Драма"],
        "countries": ["США", "Великобритания"],
    }


async def test_fallback_to_en_us_when_ru_empty(monkeypatch):
    monkeypatch.setattr("bot.services.tmdb.settings.TMDB_API_KEY", "k")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/search/movie" in request.url.path:
            lang = request.url.params.get("language")
            calls.append(lang)
            if lang == "ru-RU":
                return httpx.Response(200, json={"results": []})
            return httpx.Response(
                200, json={"results": [{"id": 42, "title": "Found"}]}
            )
        if "/movie/42" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "release_date": "2025-08-29",
                    "genres": [{"id": 35, "name": "Комедия"}],
                    "production_countries": [
                        {"iso_3166_1": "GB", "name": "United Kingdom"},
                    ],
                    "credits": {"crew": [{"job": "Director", "name": "Jay Roach"}]},
                },
            )
        return httpx.Response(404)

    tmdb.set_client(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    result = await tmdb.enrich_film("The Roses")
    assert calls == ["ru-RU", "en-US"]
    assert result == {
        "director": "Jay Roach",
        "year": "2025",
        "genres": ["Комедия"],
        "countries": ["Великобритания"],
    }


async def test_no_results_returns_none(monkeypatch):
    monkeypatch.setattr("bot.services.tmdb.settings.TMDB_API_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    tmdb.set_client(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    result = await tmdb.enrich_film("Unknown Film Xyz123")
    assert result is None


async def test_http_error_returns_none(monkeypatch):
    monkeypatch.setattr("bot.services.tmdb.settings.TMDB_API_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    tmdb.set_client(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    result = await tmdb.enrich_film("Whatever")
    assert result is None


async def test_multiple_directors_joined(monkeypatch):
    monkeypatch.setattr("bot.services.tmdb.settings.TMDB_API_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        if "/search/movie" in request.url.path:
            return httpx.Response(
                200, json={"results": [{"id": 1, "title": "X"}]}
            )
        return httpx.Response(
            200,
            json={
                "release_date": "2010-01-01",
                "genres": [],
                "credits": {
                    "crew": [
                        {"job": "Director", "name": "A"},
                        {"job": "Director", "name": "B"},
                        {"job": "Producer", "name": "C"},
                    ]
                },
            },
        )

    tmdb.set_client(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    result = await tmdb.enrich_film("X")
    assert result is not None
    assert result["director"] == "A, B"
    assert result["year"] == "2010"
    assert result["genres"] == []
    assert result["countries"] == []


async def test_country_fallback_to_english_name(monkeypatch):
    """ISO code не в _COUNTRY_RU → fallback на TMDb-имя (English)."""
    monkeypatch.setattr("bot.services.tmdb.settings.TMDB_API_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        if "/search/movie" in request.url.path:
            return httpx.Response(
                200, json={"results": [{"id": 1, "title": "X"}]}
            )
        return httpx.Response(
            200,
            json={
                "release_date": "2020-01-01",
                "genres": [],
                "production_countries": [
                    {"iso_3166_1": "ZZ", "name": "Atlantis"},
                ],
                "credits": {"crew": []},
            },
        )

    tmdb.set_client(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    result = await tmdb.enrich_film("X")
    assert result is not None
    assert result["countries"] == ["Atlantis"]
