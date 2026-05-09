"""Buildin shape: блоки лежат под ключом `data`, type — без вложенности."""

from bot.utils.md_blocks import MAX_RICH_TEXT_LEN, markdown_to_blocks_buildin


def _types(blocks):
    return [b["type"] for b in blocks]


def _text(block):
    chunks = block["data"]["rich_text"]
    return "".join(c["text"]["content"] for c in chunks)


def test_simple_paragraph_buildin_shape():
    blocks = markdown_to_blocks_buildin("Hello world")
    assert _types(blocks) == ["paragraph"]
    # Buildin: НЕТ object="block", НЕТ вложенности под именем типа.
    assert "object" not in blocks[0]
    assert "paragraph" not in blocks[0]
    assert blocks[0]["data"]["rich_text"][0]["text"]["content"] == "Hello world"


def test_headings_buildin():
    blocks = markdown_to_blocks_buildin("# H1\n## H2\n### H3")
    assert _types(blocks) == ["heading_1", "heading_2", "heading_3"]
    assert all("data" in b for b in blocks)


def test_bullet_and_numbered_buildin():
    blocks = markdown_to_blocks_buildin("- one\n- two\n1. three")
    assert _types(blocks) == [
        "bulleted_list_item",
        "bulleted_list_item",
        "numbered_list_item",
    ]
    assert [_text(b) for b in blocks] == ["one", "two", "three"]


def test_code_fence_buildin_language_in_data():
    text = "```python\nprint('x')\n```"
    blocks = markdown_to_blocks_buildin(text)
    assert _types(blocks) == ["code"]
    assert blocks[0]["data"]["language"] == "python"
    assert _text(blocks[0]) == "print('x')"


def test_quote_buildin():
    blocks = markdown_to_blocks_buildin("> quoted")
    assert _types(blocks) == ["quote"]
    assert _text(blocks[0]) == "quoted"


def test_long_paragraph_splits_in_buildin():
    long_text = "x" * (MAX_RICH_TEXT_LEN * 2 + 50)
    blocks = markdown_to_blocks_buildin(long_text)
    chunks = blocks[0]["data"]["rich_text"]
    assert len(chunks) == 3
    for c in chunks:
        assert len(c["text"]["content"]) <= MAX_RICH_TEXT_LEN
    assert "".join(c["text"]["content"] for c in chunks) == long_text


def test_empty_input_buildin():
    assert markdown_to_blocks_buildin("") == []


# --- to_do blocks ----------------------------------------------------------


def test_todo_unchecked_buildin():
    blocks = markdown_to_blocks_buildin("- [ ] foo")
    assert _types(blocks) == ["to_do"]
    assert blocks[0]["data"]["checked"] is False
    assert _text(blocks[0]) == "foo"


def test_todo_checked_buildin():
    blocks = markdown_to_blocks_buildin("- [x] done")
    assert _types(blocks) == ["to_do"]
    assert blocks[0]["data"]["checked"] is True


def test_bullet_without_brackets_stays_bullet_buildin():
    blocks = markdown_to_blocks_buildin("- foo")
    assert _types(blocks) == ["bulleted_list_item"]


# --- inline annotations ---------------------------------------------------


def _rich(block):
    return block["data"]["rich_text"]


def test_inline_bold_buildin():
    blocks = markdown_to_blocks_buildin("Hello **world**!")
    rich = _rich(blocks[0])
    assert [c["text"]["content"] for c in rich] == ["Hello ", "world", "!"]
    assert rich[1]["annotations"] == {"bold": True}


def test_inline_link_buildin():
    blocks = markdown_to_blocks_buildin("see [docs](https://example.com)")
    rich = _rich(blocks[0])
    assert rich[1]["text"]["link"] == {"url": "https://example.com"}


def test_inline_not_parsed_inside_code_fence_buildin():
    blocks = markdown_to_blocks_buildin("```\n**not bold**\n```")
    rich = blocks[0]["data"]["rich_text"]
    assert rich[0]["text"]["content"] == "**not bold**"
    assert "annotations" not in rich[0]
