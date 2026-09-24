"""Adapters from LangChain document splitters to the project's parsing contract."""

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter

from app.rag.types import ParsedBlock, ParsedDocument


_HEADERS = [("#" * level, f"h{level}") for level in range(1, 7)]


class LangChainMarkdownParser:
    def __init__(self) -> None:
        self._splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=_HEADERS, strip_headers=True
        )

    def parse(self, text: str) -> ParsedDocument:
        blocks: list[ParsedBlock] = []
        for section in self._splitter.split_text(text):
            content = section.page_content.strip()
            if content:
                blocks.append(
                    ParsedBlock(
                        text=content,
                        block_type="paragraph",
                        order=len(blocks),
                        section_path=tuple(
                            section.metadata[f"h{level}"]
                            for level in range(1, 7)
                            if f"h{level}" in section.metadata
                        ),
                    )
                )
        return ParsedDocument(blocks)


class LangChainTextParser:
    """TXT has no heading structure; hand its content to LangChain's chunker."""

    def parse(self, text: str) -> ParsedDocument:
        document = Document(page_content=text.strip())
        if not document.page_content:
            return ParsedDocument([])
        return ParsedDocument([ParsedBlock(document.page_content, "paragraph", 0)])
