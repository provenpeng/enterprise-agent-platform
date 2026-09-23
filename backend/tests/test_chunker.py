from app.rag.chunker import StructureAwareChunker
from app.rag.parsers.markdown import MarkdownParser
from app.rag.parsers.text import TextParser


def count_words(text: str) -> int:
    return len(text.split())


def make_chunker(target: int = 8, maximum: int = 10) -> StructureAwareChunker:
    return StructureAwareChunker(
        target_tokens=target, max_tokens=maximum, token_counter=count_words
    )


def test_large_section_keeps_complete_paragraphs_and_respects_limit() -> None:
    paragraphs = [f"Paragraph {index} has content." for index in range(12)]
    parsed = MarkdownParser().parse("# Policy\n\n" + "\n\n".join(paragraphs))

    chunks = make_chunker().chunk(parsed)

    assert len(chunks) > 1
    assert "\n\n".join(chunk.content for chunk in chunks) == "\n\n".join(paragraphs)
    assert all(chunk.token_count <= 10 for chunk in chunks)
    assert all(chunk.section_path == ("Policy",) for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].block_start == 1
    assert chunks[-1].block_end == 12


def test_section_boundaries_and_metadata_are_preserved() -> None:
    parsed = MarkdownParser().parse("# Policy\nIntro words.\n## A\nAlpha words.\n## B\nBeta words.")

    chunks = make_chunker().chunk(parsed)

    assert [chunk.section_path for chunk in chunks] == [
        ("Policy",), ("Policy", "A"), ("Policy", "B"),
    ]
    assert [chunk.content for chunk in chunks] == [
        "Intro words.", "Alpha words.", "Beta words.",
    ]
    assert [(chunk.block_start, chunk.block_end) for chunk in chunks] == [
        (1, 1), (3, 3), (5, 5),
    ]


def test_oversized_paragraph_splits_at_sentence_boundaries_first() -> None:
    parsed = TextParser().parse(
        "Alpha beta gamma. Delta epsilon zeta. Eta theta iota."
    )

    chunks = make_chunker(target=4, maximum=5).chunk(parsed)

    assert [chunk.content for chunk in chunks] == [
        "Alpha beta gamma.", "Delta epsilon zeta.", "Eta theta iota.",
    ]
    assert all(chunk.token_count <= 5 for chunk in chunks)
    assert all((chunk.block_start, chunk.block_end) == (0, 0) for chunk in chunks)


def test_chinese_sentence_punctuation_is_a_boundary() -> None:
    parsed = TextParser().parse("第一句内容。第二句内容！第三句内容？")
    chunker = StructureAwareChunker(target_tokens=5, max_tokens=6, token_counter=len)

    chunks = chunker.chunk(parsed)

    assert [chunk.content for chunk in chunks] == [
        "第一句内容。", "第二句内容！", "第三句内容？",
    ]


def test_oversized_sentence_uses_word_fallback() -> None:
    parsed = TextParser().parse("one two three four five six seven eight nine ten.")

    chunks = make_chunker(target=3, maximum=4).chunk(parsed)

    assert len(chunks) > 1
    assert " ".join(chunk.content for chunk in chunks) == parsed.blocks[0].text
    assert all(chunk.token_count <= 4 for chunk in chunks)


def test_single_oversized_word_uses_character_fallback() -> None:
    parsed = TextParser().parse("abcdefghij")
    chunker = StructureAwareChunker(target_tokens=3, max_tokens=4, token_counter=len)

    chunks = chunker.chunk(parsed)

    assert "".join(chunk.content for chunk in chunks) == "abcdefghij"
    assert all(chunk.token_count <= 4 for chunk in chunks)


def test_same_input_and_configuration_produce_identical_chunks() -> None:
    parsed = MarkdownParser().parse("# A\n\nOne two three. Four five six. Seven eight nine.\n\nLast paragraph.")
    chunker = make_chunker(target=4, maximum=5)

    first = chunker.chunk(parsed)
    second = chunker.chunk(parsed)

    assert first == second
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
