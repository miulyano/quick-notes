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
