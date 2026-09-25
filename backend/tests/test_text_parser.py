from app.rag.parsers.text import TextParser


def test_blank_lines_split_paragraphs_but_adjacent_lines_stay_together() -> None:
    parsed = TextParser().parse("line one\nline two\n\n\nanother paragraph\n")

    assert [block.text for block in parsed.blocks] == [
        "line one\nline two",
        "another paragraph",
    ]
    assert [block.order for block in parsed.blocks] == [0, 1]
    assert all(block.block_type == "paragraph" for block in parsed.blocks)
    assert all(
        block.heading_level is None and block.section_path == ()
        for block in parsed.blocks
    )
