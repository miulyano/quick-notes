"""TMDb (themoviedb.org) lookup для дозаполнения Director/Year/Genre фильмов.

Покрывает knowledge-cutoff LLM: TMDb знает релизы вплоть до текущего дня,
gpt-4o — только до октября 2023. Вызывается из llm_processor после
классификации type=film, если LLM оставил какое-то из полей пустым.

Поведение:
- Если TMDB_API_KEY не задан → no-op (возвращает None, как при отсутствии
  совпадения). Бот работает без TMDb, просто без дозаполнения.
- Сетевые ошибки/таймауты/невалидный ответ → лог + None, не падаем.
- Запрос идёт в `ru-RU` локали (релизы в России), при пустом результате —
  fallback в `en-US`.
- Берётся самый популярный результат (TMDb сортирует по popularity по
  умолчанию).
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from bot.config import settings


logger = logging.getLogger(__name__)


TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_TIMEOUT_SECS = 5.0


_client_override: Optional[httpx.AsyncClient] = None


def set_client(client: Optional[httpx.AsyncClient]) -> None:
    """Test hook: подмена httpx.AsyncClient (через MockTransport)."""
    global _client_override
    _client_override = client


def _new_client() -> httpx.AsyncClient:
    if _client_override is not None:
        return _client_override
    return httpx.AsyncClient(timeout=TMDB_TIMEOUT_SECS)


async def enrich_film(title: str) -> Optional[dict]:
    """Поискать фильм в TMDb по названию и вернуть Director/Year/Genres.

    Returns `{"director": str, "year": str, "genres": list[str]}` либо None,
    если фильм не найден / API недоступен / ключ не задан.

    Любые значения в результате могут быть пустыми ("", []) — caller сам
    решает, какие поля дозаполнять.
    """
    api_key = settings.TMDB_API_KEY
    if not api_key:
        return None
    title = (title or "").strip()
    if not title:
        return None

    client = _new_client()
    try:
        movie_id = await _search_movie_id(client, api_key, title)
        if movie_id is None:
            return None
        return await _fetch_movie_details(client, api_key, movie_id)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("tmdb enrich_film failed for %r: %s", title, exc)
        return None
    finally:
        if _client_override is None:
            await client.aclose()


async def _search_movie_id(
    client: httpx.AsyncClient, api_key: str, title: str
) -> Optional[int]:
    """Найти movie_id по title. Сначала ru-RU, потом en-US fallback."""
    for language in ("ru-RU", "en-US"):
        resp = await client.get(
            f"{TMDB_BASE_URL}/search/movie",
            params={
                "api_key": api_key,
                "query": title,
                "language": language,
                "include_adult": "false",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        if results:
            first = results[0]
            movie_id = first.get("id")
            if isinstance(movie_id, int):
                return movie_id
    return None


async def _fetch_movie_details(
    client: httpx.AsyncClient, api_key: str, movie_id: int
) -> dict:
    resp = await client.get(
        f"{TMDB_BASE_URL}/movie/{movie_id}",
        params={
            "api_key": api_key,
            "append_to_response": "credits",
            "language": "ru-RU",
        },
    )
    resp.raise_for_status()
    data = resp.json()

    release_date = (data.get("release_date") or "").strip()
    year = release_date[:4] if len(release_date) >= 4 and release_date[:4].isdigit() else ""

    crew = ((data.get("credits") or {}).get("crew")) or []
    directors = [
        (member.get("name") or "").strip()
        for member in crew
        if (member.get("job") or "") == "Director"
    ]
    directors = [name for name in directors if name]

    genres = [
        (g.get("name") or "").strip()
        for g in (data.get("genres") or [])
    ]
    genres = [name for name in genres if name]

    return {
        "director": ", ".join(directors),
        "year": year,
        "genres": genres,
    }
