"""Single GPT-4o call: classify type + extract properties + format body.

Real path requires OPENAI_API_KEY; without it the stub kicks in (one type
'note', body = raw input). One call instead of two saves ~half the tokens
since the model already sees the input when picking the type.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from bot.config import settings
from bot.domain.note_types import DEFAULT_TYPE, TYPES, all_keys
from bot.domain.workspaces import (
    DEFAULT_WORKSPACE,
    WORKSPACES,
    all_keys as all_workspace_keys,
)

logger = logging.getLogger(__name__)


@dataclass
class ProcessedNote:
    note_type: str
    title: str
    formatted: str                 # Markdown body (already template-rendered).
    workspace: str = DEFAULT_WORKSPACE
    properties: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)


_client_override: Any = None
_client_real: Any = None

OPENAI_TIMEOUT_SECS = 30.0
OPENAI_MAX_RETRIES = 2


class LLMError(RuntimeError):
    """Domain-level wrapper for any OpenAI / JSON-parse failure.

    Хендлеры ловят его и пишут draft.status=failed — пользователь видит ошибку
    и может /retry. Стоит между сырым openai.* и handler-слоем, чтобы handler
    не зависел от OpenAI-классов напрямую.
    """


def set_client(client: Any) -> None:
    """Test hook: inject a stand-in OpenAI client (must expose
    .chat.completions.create as AsyncMock returning the fake completion)."""
    global _client_override
    _client_override = client


def _get_client() -> Any:
    if _client_override is not None:
        return _client_override
    global _client_real
    if _client_real is None:
        from openai import AsyncOpenAI

        _client_real = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=OPENAI_TIMEOUT_SECS,
            max_retries=OPENAI_MAX_RETRIES,
        )
    return _client_real


async def close_client() -> None:
    """Закрыть httpx-сессию OpenAI при graceful shutdown.

    Idempotent: повторный вызов после close — no-op.
    """
    global _client_real
    if _client_real is not None:
        try:
            await _client_real.close()
        except Exception:
            logger.exception("OpenAI client close failed")
        _client_real = None


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _build_system_prompt() -> str:
    type_blocks = []
    for t in TYPES:
        prop_lines = "\n".join(
            f"  - {p.name} ({p.kind}): {p.llm_hint}" for p in t.properties
        )
        type_blocks.append(
            f"### {t.key}\n{t.description}\nProperties:\n{prop_lines or '  (none)'}"
        )
    types_section = "\n\n".join(type_blocks)

    workspace_lines = "\n".join(
        f"- `{w.key}` ({w.label}) — {w.description}" for w in WORKSPACES
    )

    return (
        "Ты помогаешь пользователю превращать сырые заметки (текст, транскрипт "
        "голосового, форвард) в структурированную страницу.\n\n"
        f"Сегодня: {_today_iso()}.\n\n"
        "Сделай за один проход:\n"
        "1. КЛАССИФИЦИРУЙ запись по одному из типов ниже.\n"
        "2. ВЫБЕРИ workspace, в который сохранять (см. список ниже).\n"
        "3. ИЗВЛЕКИ properties под выбранный тип.\n"
        "4. ОТФОРМАТИРУЙ тело заметки как чистый markdown (заголовки `##`, "
        "списки `-`, цитаты `>` где уместно). Не добавляй мета-информацию "
        "вроде «вот ваша заметка». Не цитируй prompt.\n\n"
        f"Типы:\n\n{types_section}\n\n"
        f"Workspaces:\n{workspace_lines}\n\n"
        f"Если не уверен в workspace — выбирай `{DEFAULT_WORKSPACE}`.\n\n"
        "Гайдлайны по конкретным типам:\n"
        "- type=task: в `markdown_body` положи 1-3 коротких параграфа с описанием "
        "задачи (контекст, мотивация, что именно надо сделать, условия успеха). "
        "Действия / шаги выноси в `extras.checklist`. В `markdown_body` НЕ дублируй "
        "пункты чек-листа — только описание. Если описания в исходном тексте нет — "
        "оставь body пустым, чек-лист сам по себе.\n"
        "- type=meeting: подвид `sync` — это регулярная встреча команды для сверки "
        "статусов, выявления блокеров, назначения задач. Триггеры: «синк», «standup», "
        "«daily», «weekly», «status», «команда собралась», «обсудили статусы», «блокеры». "
        "Если запись выглядит как sync — верни `type=meeting` + `extras.kind=\"sync\"`. "
        "ВЕСЬ контент для sync положи в `markdown_body`, **сохраняя исходную "
        "иерархию**: если в тексте есть видимая группировка (по людям, зонам, "
        "проектам, темам) — отрази её как `### Заголовок группы` + список "
        "буллетов `- пункт` под каждым заголовком. НЕ схлопывай несколько буллетов "
        "одной группы в одну строку через запятую — каждый исходный пункт отдельной "
        "строкой буллета. Если структуры нет — простой плоский список буллетов или "
        "абзацы. Для sync поля `extras.agenda/decisions/status_updates/blockers` "
        "НЕ используй — они только дублируют body. Можно заполнить `extras.action_items` "
        "(чисто действия, кто что делает), если они явно выделяются.\n"
        "  Обычный митинг (kick-off, обсуждение, ретро) — `extras.kind=\"meeting\"` "
        "(default), используй agenda/decisions/action_items.\n"
        "- type=meeting и type=1on1: для `properties.Date` используй ISO-дату встречи "
        "из текста, иначе сегодняшнюю (см. «Сегодня» выше). В `title` ОБЯЗАТЕЛЬНО "
        "добавь дату в скобках в конце: `«Тема (YYYY-MM-DD)»`. Общая длина title ≤ 80.\n\n"
        "Верни СТРОГО JSON со схемой:\n"
        "{\n"
        '  "type": "<один из ключей типов>",\n'
        '  "workspace": "<один из ключей workspaces>",\n'
        '  "title": "<строка ≤80 символов>",\n'
        '  "properties": { "<имя property>": <value>, ... },\n'
        '  "extras": {\n'
        '    "checklist": ["..."],        // для type=task\n'
        '    "kind": "meeting"|"sync",    // для type=meeting (default "meeting")\n'
        '    "agenda": ["..."],           // для type=meeting kind=meeting\n'
        '    "decisions": ["..."],        // для type=meeting kind=meeting\n'
        '    "action_items": ["..."],     // для type=meeting (оба kind)\n'
        '    "topics": ["..."],           // для type=1on1\n'
        '    "follow_ups": ["..."]        // для type=1on1\n'
        '  },\n'
        '  "markdown_body": "<основное тело заметки markdown>"\n'
        "}\n\n"
        "Все поля extras — опциональные, опускай если не применимы. "
        "Properties: используй формат значений соответствующий kind:\n"
        "- title/rich_text → строка\n"
        "- select → строка (одно значение)\n"
        "- multi_select → массив строк (1-3 элемента, может быть пустым)\n"
        "- date → ISO 8601 строка (YYYY-MM-DD), null если неизвестно\n"
        "- checkbox → bool"
    )


async def _process_real(raw_text: str) -> ProcessedNote:
    client = _get_client()
    system_prompt = _build_system_prompt()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        response_format={"type": "json_object"},
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ],
    )
    content = response.choices[0].message.content or "{}"
    payload = json.loads(content)

    note_type = payload.get("type") or DEFAULT_TYPE
    if note_type not in all_keys():
        logger.warning("LLM returned unknown type=%r, falling back to %s", note_type, DEFAULT_TYPE)
        note_type = DEFAULT_TYPE

    workspace = payload.get("workspace") or DEFAULT_WORKSPACE
    if workspace not in all_workspace_keys():
        logger.warning(
            "LLM returned unknown workspace=%r, falling back to %s",
            workspace,
            DEFAULT_WORKSPACE,
        )
        workspace = DEFAULT_WORKSPACE

    title = (payload.get("title") or "Без названия").strip()[:80]
    properties = payload.get("properties") or {}
    extras = payload.get("extras") or {}
    body = (payload.get("markdown_body") or "").strip() or raw_text

    # Render template here so handlers stay dumb. Keeps LLM-output and
    # template logic close together.
    from bot.domain.templates import render

    formatted = render(note_type, body, extras)

    return ProcessedNote(
        note_type=note_type,
        title=title,
        formatted=formatted,
        workspace=workspace,
        properties=properties if isinstance(properties, dict) else {},
        extras=extras if isinstance(extras, dict) else {},
    )


async def _process_stub(raw_text: str) -> ProcessedNote:
    text = raw_text.strip()
    first_line = text.split("\n", 1)[0]
    title = first_line[:80] if first_line else "Без названия"
    return ProcessedNote(
        note_type=DEFAULT_TYPE,
        title=title,
        formatted=text,
        workspace=DEFAULT_WORKSPACE,
    )


async def process(raw_text: str) -> ProcessedNote:
    """Real path при openai_enabled — иначе stub (single 'note' type).

    Real-path ошибки (network/timeout/rate-limit/невалидный JSON) пробрасываются
    как LLMError. Молчаливого fallback на stub НЕТ: handler ставит draft.failed
    и пользователь может /retry.
    """
    if not settings.openai_enabled:
        return await _process_stub(raw_text)
    try:
        return await _process_real(raw_text)
    except LLMError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.exception("LLM response parse failed")
        raise LLMError(f"LLM response parse failed: {exc}") from exc
    except Exception as exc:
        # OpenAI SDK throws openai.APIError / APITimeoutError / RateLimitError
        # и пр. — мы их не импортируем, чтобы не плодить hard-зависимость на
        # классы SDK; ловим широко, но с явным wrapping в LLMError.
        logger.exception("OpenAI request failed")
        raise LLMError(f"OpenAI request failed: {exc}") from exc


# Map-reduce path: документы могут давать тексты, не помещающиеся в один LLM-промпт
# с запасом на system prompt и JSON-ответ. Порог взят с большим запасом — gpt-4o
# имеет 128k tokens context, 40k символов ≈ 12k токенов.
LONG_TEXT_THRESHOLD_CHARS = 40_000
SUMMARY_CHUNK_CHARS = 30_000
SUMMARY_MAX_TOKENS = 1500


async def process_long(
    raw_text: str,
    *,
    on_fraction: Optional[Callable[[float], Awaitable[None]]] = None,
) -> ProcessedNote:
    """Single-shot `process` для коротких текстов; map-reduce для длинных.

    Длинные тексты бьются на куски, каждый кусок сжимается отдельным LLM-вызовом
    (plain-text summary с упором на agenda / decisions / action items / blockers),
    итоговая склейка прогоняется через обычный `process` для классификации.
    """
    if len(raw_text) <= LONG_TEXT_THRESHOLD_CHARS or not settings.openai_enabled:
        result = await process(raw_text)
        if on_fraction:
            await on_fraction(1.0)
        return result

    chunks = _split_for_summary(raw_text, SUMMARY_CHUNK_CHARS)
    summaries: list[str] = []
    total_steps = len(chunks) + 1
    for i, chunk in enumerate(chunks, 1):
        summaries.append(await _summarize_chunk(chunk, idx=i, total=len(chunks)))
        if on_fraction:
            await on_fraction(i / total_steps)

    consolidated = "\n\n".join(
        f"## Section {i}\n{s}" for i, s in enumerate(summaries, 1)
    )
    result = await process(consolidated)
    if on_fraction:
        await on_fraction(1.0)
    return result


def _split_for_summary(text: str, chunk_size: int) -> list[str]:
    """Бьём по \\n\\n, если кусок слишком большой — по \\n, в крайнем случае — по символам."""
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    buf = ""
    for paragraph in text.split("\n\n"):
        candidate = paragraph if not buf else f"{buf}\n\n{paragraph}"
        if len(candidate) <= chunk_size:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(paragraph) <= chunk_size:
            buf = paragraph
        else:
            chunks.extend(_split_by_lines(paragraph, chunk_size))
    if buf:
        chunks.append(buf)
    return chunks


def _split_by_lines(text: str, chunk_size: int) -> list[str]:
    chunks: list[str] = []
    buf = ""
    for line in text.split("\n"):
        candidate = line if not buf else f"{buf}\n{line}"
        if len(candidate) <= chunk_size:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(line) <= chunk_size:
            buf = line
        else:
            for i in range(0, len(line), chunk_size):
                chunks.append(line[i : i + chunk_size])
    if buf:
        chunks.append(buf)
    return chunks


async def _summarize_chunk(chunk: str, *, idx: int, total: int) -> str:
    client = _get_client()
    system_prompt = (
        f"Перед тобой часть {idx}/{total} большого документа "
        "(транскрипт встречи, агенда, повестка или подобное). "
        "Сожми в маркированный список ключевых пунктов на русском. "
        "Сохрани: agenda items, decisions, action items (кто/что/когда), "
        "status updates, blockers, прямые цитаты решений. Не выдумывай факты. "
        "Не добавляй мета-комментариев — только содержание."
    )
    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            temperature=0.2,
            max_tokens=SUMMARY_MAX_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": chunk},
            ],
        )
    except Exception as exc:
        logger.exception("OpenAI summary chunk %s/%s failed", idx, total)
        raise LLMError(f"OpenAI summary failed: {exc}") from exc

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise LLMError(f"empty summary for chunk {idx}/{total}")
    return content
