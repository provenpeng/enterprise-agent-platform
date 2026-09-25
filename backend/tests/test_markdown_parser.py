from app.rag.parsers.markdown import MarkdownParser


def test_heading_hierarchy_and_source_order() -> None:
    parsed = MarkdownParser().parse(
        "# A\nIntro.\n## B\n### C\nUnder C.\n## D\nUnder D.\n# E\nUnder E."
    )

    assert [block.order for block in parsed.blocks] == list(range(len(parsed.blocks)))
    assert [block.block_type for block in parsed.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "heading",
        "paragraph",
        "heading",
        "paragraph",
        "heading",
        "paragraph",
    ]
    assert [
        block.heading_level for block in parsed.blocks if block.block_type == "heading"
    ] == [
        1,
        2,
        3,
        2,
        1,
    ]
    assert [
        block.section_path for block in parsed.blocks if block.block_type == "paragraph"
    ] == [
        ("A",),
        ("A", "B", "C"),
        ("A", "D"),
        ("E",),
    ]


def test_paragraphs_keep_source_order_and_group_lines() -> None:
    parsed = MarkdownParser().parse(
        "Before heading.\n\n# Title ###\nfirst line\nsecond line\n\n## Next\nLast."
    )

    assert [block.order for block in parsed.blocks] == [0, 1, 2, 3, 4]
    assert [block.text for block in parsed.blocks] == [
        "Before heading.",
        "Title",
        "first line\nsecond line",
        "Next",
        "Last.",
    ]
    assert parsed.blocks[2].section_path == ("Title",)
    assert parsed.blocks[4].section_path == ("Title", "Next")
