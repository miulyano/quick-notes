"""BuildinSink: shape запроса (parent с type, properties с type, blocks под data)
+ chunking длинных заметок через PATCH /v1/blocks/{page_id}/children.

Используем httpx.MockTransport — никаких реальных сетевых вызовов.
"""

from __future__ import annotations

import json

import httpx
import pytest

from bot.services.sinks import buildin as buildin_sink
from bot.storage.drafts import Draft


def _draft(
    *,
    note_type: str = "note",
    workspace: str = "personal",
    formatted: str = "Hello",
    properties: dict | None = None,
    title: str = "T",
) -> Draft:
    return Draft(
        id="d1",
        user_id=1,
        chat_id=1,
        message_id=1,
        preview_msg_id=None,
        status="awaiting_confirm",
        kind="text",
        raw_payload="raw",
        transcribed=None,
        note_type=note_type,
        formatted=formatted,
        title=title,
        properties=json.dumps(properties or {}),
        error=None,
        created_at=0,
        updated_at=0,
        workspace=workspace,
    )


@pytest.fixture(autouse=True)
def _reset_buildin_state():
    buildin_sink.set_failure_injector(None)
    buildin_sink.set_client(None)
    yield
    buildin_sink.set_failure_injector(None)
    buildin_sink.set_client(None)


async def test_create_page_buildin_shape(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.buildin.settings.BUILDIN_TOKEN", "k")
    monkeypatch.setenv("BUILDIN_DB_PERSONAL_NOTE", "db-uuid-personal-note")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "page-123", "url": "https://buildin.ai/p/123"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="https://api.buildin.ai", transport=transport)
    buildin_sink.set_client(client)

    page_ref = await buildin_sink.create_page(_draft(formatted="# H1\n\npara"))
    assert page_ref.id == "page-123"
    assert page_ref.url == "https://buildin.ai/p/123"

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/pages"
    body = captured["body"]
    # Buildin parent: явный type-дискриминатор.
    assert body["parent"] == {"type": "database_id", "database_id": "db-uuid-personal-note"}
    # Properties: type tagged.
    assert body["properties"]["Name"]["type"] == "title"
    assert body["properties"]["CreatedAt"]["type"] == "date"
    # Children: контент под `data`, не под именем типа.
    blocks = body["children"]
    assert blocks[0]["type"] == "heading_1"
    assert "data" in blocks[0]
    assert "heading_1" not in blocks[0]


async def test_create_page_uses_workspace_routing(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.buildin.settings.BUILDIN_TOKEN", "k")
    monkeypatch.setenv("BUILDIN_DB_WORK_TASK", "work-task-uuid")
    monkeypatch.setenv("BUILDIN_DB_PERSONAL_TASK", "personal-task-uuid")

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "p"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="https://api.buildin.ai", transport=transport)
    buildin_sink.set_client(client)

    await buildin_sink.create_page(_draft(note_type="task", workspace="work"))
    await buildin_sink.create_page(_draft(note_type="task", workspace="personal"))

    assert captured[0]["parent"]["database_id"] == "work-task-uuid"
    assert captured[1]["parent"]["database_id"] == "personal-task-uuid"


async def test_chunking_long_pages_appends_children(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.buildin.settings.BUILDIN_TOKEN", "k")
    monkeypatch.setattr("bot.services.sinks.buildin.MAX_BLOCKS_PER_REQUEST", 5)
    monkeypatch.setenv("BUILDIN_DB_PERSONAL_NOTE", "db1")

    requests: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"id": "p1"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="https://api.buildin.ai", transport=transport)
    buildin_sink.set_client(client)

    body = "\n\n".join(f"para {i}" for i in range(13))  # 13 параграфов
    await buildin_sink.create_page(_draft(formatted=body))

    # POST /v1/pages с первыми 5, затем 2 PATCH'а: 5 и 3.
    assert requests[0][0] == "POST"
    assert requests[0][1] == "/v1/pages"
    assert len(requests[0][2]["children"]) == 5

    assert requests[1][0] == "PATCH"
    assert requests[1][1] == "/v1/blocks/p1/children"
    assert len(requests[1][2]["children"]) == 5

    assert requests[2][0] == "PATCH"
    assert requests[2][1] == "/v1/blocks/p1/children"
    assert len(requests[2][2]["children"]) == 3


async def test_no_database_configured_raises(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.buildin.settings.BUILDIN_TOKEN", "k")
    monkeypatch.delenv("BUILDIN_DB_PERSONAL_NOTE", raising=False)
    monkeypatch.delenv("BUILDIN_DB_NOTE", raising=False)
    monkeypatch.setattr("bot.services.sinks.buildin.settings.BUILDIN_DB_DEFAULT", None)

    with pytest.raises(RuntimeError, match="no Buildin database configured"):
        await buildin_sink.create_page(_draft(note_type="note", workspace="personal"))


async def test_stub_when_no_token(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.buildin.settings.BUILDIN_TOKEN", None)

    page_ref = await buildin_sink.create_page(_draft())
    assert page_ref.id.startswith("stub-page-")
    assert page_ref.url is None


async def test_users_me_validates_via_get(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.buildin.settings.BUILDIN_TOKEN", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/users/me"
        return httpx.Response(200, json={"id": "bot-1", "name": "TestBot"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="https://api.buildin.ai", transport=transport)
    buildin_sink.set_client(client)

    me = await buildin_sink.users_me()
    assert me["name"] == "TestBot"


async def test_buildin_error_on_4xx(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.buildin.settings.BUILDIN_TOKEN", "k")
    monkeypatch.setenv("BUILDIN_DB_PERSONAL_NOTE", "db1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="https://api.buildin.ai", transport=transport)
    buildin_sink.set_client(client)

    with pytest.raises(buildin_sink.BuildinError) as exc_info:
        await buildin_sink.create_page(_draft())
    assert exc_info.value.status == 401


async def test_failure_injector_runs(monkeypatch):
    monkeypatch.setattr("bot.services.sinks.buildin.settings.BUILDIN_TOKEN", "k")

    async def boom(_d):
        raise RuntimeError("transient")

    buildin_sink.set_failure_injector(boom)
    with pytest.raises(RuntimeError, match="transient"):
        await buildin_sink.create_page(_draft())
