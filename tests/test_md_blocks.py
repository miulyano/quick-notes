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
