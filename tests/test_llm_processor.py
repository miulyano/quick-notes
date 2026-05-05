from bot.services import llm_processor


async def test_stub_uses_first_line_as_title():
    p = await llm_processor.process("Title line\nbody body")
    assert p.note_type == "note"
    assert p.title == "Title line"
    assert p.formatted == "Title line\nbody body"


async def test_stub_truncates_long_title():
    long_line = "a" * 200
    p = await llm_processor.process(long_line)
    assert len(p.title) == 80


async def test_stub_handles_empty():
    p = await llm_processor.process("   ")
    assert p.title == "Без названия"
