from bot.domain.templates import render


def test_default_passthrough():
    assert render("personal", "hello world") == "hello world"


def test_note_passthrough():
    assert render("note", "hello") == "hello"


def test_task_with_checklist():
    out = render("task", "Подготовить релиз", {"checklist": ["bump VERSION", "tag"]})
    assert "## Чек-лист" in out
    assert "- [ ] bump VERSION" in out
    assert "- [ ] tag" in out
    assert out.index("Подготовить релиз") < out.index("## Чек-лист")


def test_task_description_before_checklist_multiline():
    body = "Цель: выкатить v1.2.\n\nКонтекст: команда ждёт релиз для демо в пятницу."
    out = render("task", body, {"checklist": ["bump VERSION", "tag", "push"]})
    assert "Цель: выкатить v1.2." in out
    assert "Контекст: команда ждёт релиз" in out
    assert out.index("Контекст") < out.index("## Чек-лист")
    assert "- [ ] bump VERSION" in out


def test_task_no_checklist():
    assert render("task", "Просто задача") == "Просто задача"


def test_meeting_full():
    out = render(
        "meeting",
        "Обсудили roadmap.",
        {
            "agenda": ["Q3 plan", "Hiring"],
            "decisions": ["Push deadline by 1w"],
            "action_items": ["Update spec", "Notify team"],
        },
    )
    assert "## Agenda" in out
    assert "## Discussion" in out
    assert "Обсудили roadmap." in out
    assert "## Decisions" in out
    assert "## Action items" in out
    assert "- [ ] Update spec" in out


def test_meeting_minimal():
    assert render("meeting", "kick-off chat") == "kick-off chat"


def test_meeting_sync_passthrough_body():
    body = "### Алиса\n- auth готов\n- миграция\n\n### Боб\n- блокер на фронте"
    out = render("meeting", body, {"kind": "sync"})
    # Шаблон ничего не дописывает — иерархию строит LLM в body.
    assert out == body
    # Старые секционные заголовки больше не появляются.
    assert "## Status updates" not in out
    assert "## Notes" not in out
    assert "## Blockers" not in out


def test_meeting_sync_with_action_items():
    body = "### Алиса\n- auth готов\n\n### Боб\n- миграция"
    out = render(
        "meeting",
        body,
        {"kind": "sync", "action_items": ["Пингануть фронт", "Снять блокер"]},
    )
    assert body in out
    assert out.index("Боб") < out.index("## Action items")
    assert "- [ ] Пингануть фронт" in out
    assert "- [ ] Снять блокер" in out
    assert "## Status updates" not in out
    assert "## Notes" not in out


def test_meeting_sync_legacy_status_updates_ignored():
    """Старая форма structured extras для sync больше не рендерится — body главный."""
    out = render(
        "meeting",
        "Тело синка",
        {
            "kind": "sync",
            "status_updates": ["Алиса: auth"],
            "blockers": ["Жду"],
        },
    )
    assert out == "Тело синка"
    assert "Status updates" not in out
    assert "Blockers" not in out


def test_meeting_sync_minimal_falls_back_to_body():
    assert render("meeting", "Просто синк", {"kind": "sync"}) == "Просто синк"


def test_meeting_kind_meeting_default_uses_classic_render():
    out = render(
        "meeting",
        "Обсудили roadmap.",
        {"kind": "meeting", "decisions": ["Push deadline"]},
    )
    assert "## Decisions" in out
    assert "## Status updates" not in out


def test_1on1_full():
    out = render(
        "1on1",
        "Обсудили рост и блокеры.",
        {"topics": ["Career path"], "follow_ups": ["Share OKR doc"]},
    )
    assert "## Topics" in out
    assert "## Notes" in out
    assert "## Follow-ups" in out
    assert "- [ ] Share OKR doc" in out


def test_unknown_type_falls_to_default():
    assert render("nonexistent", "body") == "body"


def test_book_passthrough():
    body = "Отличная книга про когнитивные искажения. Запомнить главу 3."
    assert render("book", body) == body


def test_film_passthrough():
    body = "Хороший фильм. Финал слабоват."
    assert render("film", body) == body
