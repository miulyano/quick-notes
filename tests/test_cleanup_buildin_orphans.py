"""scripts/cleanup_buildin_orphans: archive wrapper-pages по BUILDIN_DB_* envs."""

import contextlib

import httpx
import pytest

from scripts.cleanup_buildin_orphans import run


def _make_handler(parents: dict[str, dict], archived: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.startswith("/v1/databases/"):
            db_id = path.split("/")[-1]
            if db_id in parents:
                return httpx.Response(200, json={"parent": parents[db_id]})
            return httpx.Response(404, json={"error": "not_found"})
        if request.method == "PATCH" and path.startswith("/v1/pages/"):
            page_id = path.split("/")[-1]
            archived.append(page_id)
            return httpx.Response(200, json={"id": page_id, "archived": True})
        return httpx.Response(500, json={"error": "unexpected"})

    return handler


@contextlib.asynccontextmanager
async def _client_ctx(handler):
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.buildin.ai") as c:
        yield c


def _factory(handler):
    def factory():
        return _client_ctx(handler)

    return factory


@pytest.fixture(autouse=True)
def _set_buildin_token(monkeypatch):
    monkeypatch.setattr("bot.config.settings.BUILDIN_TOKEN", "test-token")
    # Чистим все BUILDIN_DB_* перед каждым тестом, чтобы не наследовать .env.
    for key in list(__import__("os").environ):
        if key.startswith("BUILDIN_DB_"):
            monkeypatch.delenv(key, raising=False)


@pytest.mark.asyncio
async def test_archives_wrappers_for_envs(monkeypatch):
    monkeypatch.setenv("BUILDIN_DB_PERSONAL_NOTE", "db-1")
    monkeypatch.setenv("BUILDIN_DB_WORK_TASK", "db-2")

    archived: list[str] = []
    handler = _make_handler(
        {
            "db-1": {"type": "page_id", "page_id": "wrap-1"},
            "db-2": {"type": "page_id", "page_id": "wrap-2"},
        },
        archived,
    )

    code = await run(None, None, dry_run=False, client_factory=_factory(handler))

    assert code == 0
    assert sorted(archived) == ["wrap-1", "wrap-2"]


@pytest.mark.asyncio
async def test_dry_run_does_not_call_api(monkeypatch):
    monkeypatch.setenv("BUILDIN_DB_PERSONAL_NOTE", "db-1")

    archived: list[str] = []
    handler = _make_handler({"db-1": {"type": "page_id", "page_id": "wrap-1"}}, archived)

    code = await run(None, None, dry_run=True, client_factory=_factory(handler))

    assert code == 0
    assert archived == []


@pytest.mark.asyncio
async def test_per_workspace_filter(monkeypatch):
    monkeypatch.setenv("BUILDIN_DB_PERSONAL_NOTE", "db-personal")
    monkeypatch.setenv("BUILDIN_DB_WORK_TASK", "db-work")

    archived: list[str] = []
    handler = _make_handler(
        {
            "db-personal": {"type": "page_id", "page_id": "wrap-p"},
            "db-work": {"type": "page_id", "page_id": "wrap-w"},
        },
        archived,
    )

    code = await run("personal", None, dry_run=False, client_factory=_factory(handler))

    assert code == 0
    assert archived == ["wrap-p"]


@pytest.mark.asyncio
async def test_failure_on_one_pair_does_not_break_others(monkeypatch):
    monkeypatch.setenv("BUILDIN_DB_PERSONAL_NOTE", "db-ok")
    monkeypatch.setenv("BUILDIN_DB_PERSONAL_TASK", "db-missing")

    archived: list[str] = []
    handler = _make_handler(
        {"db-ok": {"type": "page_id", "page_id": "wrap-ok"}},
        archived,
    )

    code = await run(None, None, dry_run=False, client_factory=_factory(handler))

    assert code == 1  # failures > 0
    assert archived == ["wrap-ok"]


@pytest.mark.asyncio
async def test_no_envs_returns_zero():
    code = await run(None, None, dry_run=False, client_factory=lambda: None)
    assert code == 0
