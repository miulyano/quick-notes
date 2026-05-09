from bot.utils.md_blocks import MAX_RICH_TEXT_LEN, markdown_to_blocks


def _types(blocks):
    return [b["type"] for b in blocks]


def _text(block):
    chunks = block[block["type"]]["rich_text"]
    return "".join(c["text"]["content"] for c in chunks)


def test_simple_paragraph():
    blocks = markdown_to_blocks("Hello world")
    assert _types(blocks) == ["paragraph"]
    assert _text(blocks[0]) == "Hello world"


def test_paragraphs_separated_by_blank_line():
    blocks = markdown_to_blocks("First.\n\nSecond.")
    assert _types(blocks) == ["paragraph", "paragraph"]
    assert _text(blocks[0]) == "First."
    assert _text(blocks[1]) == "Second."


def test_headings():
    blocks = markdown_to_blocks("# H1\n## H2\n### H3")
    assert _types(blocks) == ["heading_1", "heading_2", "heading_3"]
    assert _text(blocks[0]) == "H1"
    assert _text(blocks[1]) == "H2"
    assert _text(blocks[2]) == "H3"


def test_bullet_list():
    blocks = markdown_to_blocks("- one\n- two\n* three")
    assert _types(blocks) == ["bulleted_list_item"] * 3
    assert [_text(b) for b in blocks] == ["one", "two", "three"]


def test_numbered_list():
    blocks = markdown_to_blocks("1. one\n2. two")
    assert _types(blocks) == ["numbered_list_item"] * 2


def test_quote():
    blocks = markdown_to_blocks("> quoted line")
    assert _types(blocks) == ["quote"]
    assert _text(blocks[0]) == "quoted line"


def test_code_fence():
    text = "```python\nprint('x')\n```"
    blocks = markdown_to_blocks(text)
    assert _types(blocks) == ["code"]
    assert blocks[0]["code"]["language"] == "python"
    assert _text(blocks[0]) == "print('x')"


def test_long_paragraph_splits_rich_text():
    long_text = "x" * (MAX_RICH_TEXT_LEN * 2 + 100)
    blocks = markdown_to_blocks(long_text)
    assert _types(blocks) == ["paragraph"]
    chunks = blocks[0]["paragraph"]["rich_text"]
    assert len(chunks) == 3
    # Every chunk is within the per-element cap.
    for c in chunks:
        assert len(c["text"]["content"]) <= MAX_RICH_TEXT_LEN
    # Content reassembles to the original.
    assert "".join(c["text"]["content"] for c in chunks) == long_text


def test_empty_input():
    assert markdown_to_blocks("") == []


def test_mixed_content():
    text = "# Title\n\nIntro paragraph.\n\n- a\n- b\n\n> wisdom"
    blocks = markdown_to_blocks(text)
    assert _types(blocks) == [
        "heading_1",
        "paragraph",
        "bulleted_list_item",
        "bulleted_list_item",
        "quote",
    ]


# --- to_do blocks ----------------------------------------------------------


def test_todo_unchecked():
    blocks = markdown_to_blocks("- [ ] foo")
    assert _types(blocks) == ["to_do"]
    assert blocks[0]["to_do"]["checked"] is False
    assert _text(blocks[0]) == "foo"


def test_todo_checked_lower():
    blocks = markdown_to_blocks("- [x] done")
    assert _types(blocks) == ["to_do"]
    assert blocks[0]["to_do"]["checked"] is True
    assert _text(blocks[0]) == "done"


def test_todo_checked_upper():
    blocks = markdown_to_blocks("- [X] done")
    assert _types(blocks) == ["to_do"]
    assert blocks[0]["to_do"]["checked"] is True


def test_bullet_without_brackets_stays_bullet():
    blocks = markdown_to_blocks("- foo")
    assert _types(blocks) == ["bulleted_list_item"]


def test_todo_via_asterisk_bullet():
    blocks = markdown_to_blocks("* [ ] foo")
    assert _types(blocks) == ["to_do"]
    assert blocks[0]["to_do"]["checked"] is False


def test_todo_checklist_block():
    text = "## Чек-лист\n\n- [ ] one\n- [ ] two\n- [x] three"
    blocks = markdown_to_blocks(text)
    assert _types(blocks) == ["heading_2", "to_do", "to_do", "to_do"]
    assert [b["to_do"]["checked"] for b in blocks[1:]] == [False, False, True]


# --- inline annotations ----------------------------------------------------


def _rich(block):
    return block[block["type"]]["rich_text"]


def test_inline_bold():
    blocks = markdown_to_blocks("Hello **world**!")
    rich = _rich(blocks[0])
    contents = [c["text"]["content"] for c in rich]
    assert contents == ["Hello ", "world", "!"]
    assert "annotations" not in rich[0]
    assert rich[1]["annotations"] == {"bold": True}
    assert "annotations" not in rich[2]


def test_inline_italic_asterisk():
    blocks = markdown_to_blocks("a *b* c")
    rich = _rich(blocks[0])
    assert [c["text"]["content"] for c in rich] == ["a ", "b", " c"]
    assert rich[1]["annotations"] == {"italic": True}


def test_inline_italic_underscore():
    blocks = markdown_to_blocks("a _b_ c")
    rich = _rich(blocks[0])
    assert rich[1]["text"]["content"] == "b"
    assert rich[1]["annotations"] == {"italic": True}


def test_inline_underscore_inside_word_not_italic():
    blocks = markdown_to_blocks("snake_case_word")
    rich = _rich(blocks[0])
    assert len(rich) == 1
    assert rich[0]["text"]["content"] == "snake_case_word"
    assert "annotations" not in rich[0]


def test_inline_code():
    blocks = markdown_to_blocks("use `foo()` here")
    rich = _rich(blocks[0])
    assert rich[1]["text"]["content"] == "foo()"
    assert rich[1]["annotations"] == {"code": True}


def test_inline_link():
    blocks = markdown_to_blocks("see [docs](https://example.com)")
    rich = _rich(blocks[0])
    link_token = rich[1]
    assert link_token["text"]["content"] == "docs"
    assert link_token["text"]["link"] == {"url": "https://example.com"}


def test_inline_bold_in_bullet():
    blocks = markdown_to_blocks("- **Имя Фамилия** — meta")
    assert _types(blocks) == ["bulleted_list_item"]
    rich = _rich(blocks[0])
    assert rich[0]["text"]["content"] == "Имя Фамилия"
    assert rich[0]["annotations"] == {"bold": True}
    assert rich[1]["text"]["content"] == " — meta"


def test_inline_bold_in_todo():
    blocks = markdown_to_blocks("- [ ] **bold** task")
    assert _types(blocks) == ["to_do"]
    rich = _rich(blocks[0])
    assert rich[0]["text"]["content"] == "bold"
    assert rich[0]["annotations"] == {"bold": True}
    assert rich[1]["text"]["content"] == " task"


def test_inline_long_bold_chunked():
    long_bold = "x" * (MAX_RICH_TEXT_LEN + 50)
    blocks = markdown_to_blocks(f"**{long_bold}**")
    rich = _rich(blocks[0])
    assert len(rich) == 2
    for c in rich:
        assert len(c["text"]["content"]) <= MAX_RICH_TEXT_LEN
        assert c["annotations"] == {"bold": True}
    assert "".join(c["text"]["content"] for c in rich) == long_bold


def test_inline_not_parsed_inside_code_fence():
    text = "```python\n**not bold**\n```"
    blocks = markdown_to_blocks(text)
    assert _types(blocks) == ["code"]
    rich = blocks[0]["code"]["rich_text"]
    assert rich[0]["text"]["content"] == "**not bold**"
    assert "annotations" not in rich[0]
