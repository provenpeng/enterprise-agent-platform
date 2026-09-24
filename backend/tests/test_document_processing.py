import pytest

from app.core.config import Settings
from app.rag.processing import create_document_processor
from app.services.document_processing import document_processor_from_settings


MARKDOWN = (
    "# Refund policy\n\nRequests are accepted within thirty days.\n\n"
    "## Final sale\n\nFinal sale orders cannot be refunded."
)


@pytest.mark.parametrize("backend", ["manual", "langchain"])
@pytest.mark.parametrize(
    ("file_type", "text", "expected_sections"),
    [
        (
            "text/markdown",
            MARKDOWN,
            [("Refund policy",), ("Refund policy", "Final sale")],
        ),
        ("text/plain", "First paragraph.\n\nSecond paragraph.", [()]),
    ],
)
def test_backends_share_chunk_contract_and_preserve_source(
    backend: str, file_type: str, text: str, expected_sections: list[tuple[str, ...]]
) -> None:
    processor = create_document_processor(
        backend=backend,
        file_type=file_type,
        target_tokens=10,
        max_tokens=12,
        token_counter=lambda value: len(value.split()),
    )

    parsed = processor.parse(text)
    chunks = processor.process(text)

    assert chunks == processor.process(text)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert set(chunk.section_path for chunk in chunks) == set(expected_sections)
    assert all(0 < chunk.token_count <= 12 for chunk in chunks)
    assert all(chunk.block_start is not None and chunk.block_end is not None for chunk in chunks)
    assert all(chunk.block_start <= chunk.block_end < len(parsed.blocks) for chunk in chunks)
    assert all(chunk.content.strip() for chunk in chunks)


@pytest.mark.parametrize("backend", ["manual", "langchain"])
def test_settings_select_backend_without_changing_caller(backend: str) -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://example:example@localhost/example",
        document_processing_backend=backend,
    )
    processor = document_processor_from_settings(
        settings,
        file_type="text/markdown",
        target_tokens=20,
        max_tokens=30,
        token_counter=len,
    )

    assert processor.process("# Rules\n\nRefunds require approval.")[0].section_path == ("Rules",)
    assert ("langchain" in type(processor.parser).__module__) is (backend == "langchain")


@pytest.mark.parametrize("backend", ["manual", "langchain"])
def test_empty_input_has_no_chunks(backend: str) -> None:
    processor = create_document_processor(
        backend=backend,
        file_type="text/plain",
        target_tokens=5,
        max_tokens=10,
        token_counter=len,
    )

    assert processor.process(" \n\n ") == []


def test_unsupported_format_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="not available"):
        create_document_processor(
            backend="langchain",
            file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            target_tokens=5,
            max_tokens=10,
            token_counter=len,
        )


def test_langchain_parser_keeps_fenced_heading_in_parent_section() -> None:
    processor = create_document_processor(
        backend="langchain",
        file_type="text/markdown",
        target_tokens=100,
        max_tokens=120,
        token_counter=len,
    )

    chunks = processor.process("# Rules\n\n```python\n# code comment\n```\n\nApply the rule.")

    assert chunks
    assert all(chunk.section_path == ("Rules",) for chunk in chunks)
    assert any("# code comment" in chunk.content for chunk in chunks)
