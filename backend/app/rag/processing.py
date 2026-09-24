"""Stable entry point for interchangeable document processing implementations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.rag.chunker import StructureAwareChunker
from app.rag.langchain_chunker import LangChainChunker
from app.rag.parsers.base import DocumentChunker, DocumentParser
from app.rag.parsers.langchain import LangChainMarkdownParser, LangChainTextParser
from app.rag.parsers.markdown import MarkdownParser
from app.rag.parsers.text import TextParser
from app.rag.types import ChunkCandidate, ParsedDocument


ProcessingBackend = Literal["manual", "langchain"]


@dataclass(frozen=True)
class DocumentProcessor:
    parser: DocumentParser
    chunker: DocumentChunker

    def parse(self, text: str) -> ParsedDocument:
        return self.parser.parse(text)

    def process(self, text: str) -> list[ChunkCandidate]:
        return self.chunker.chunk(self.parse(text))


def create_document_processor(
    *,
    backend: ProcessingBackend,
    file_type: str,
    target_tokens: int,
    max_tokens: int,
    token_counter: Callable[[str], int],
) -> DocumentProcessor:
    if file_type not in {"text/plain", "text/markdown"}:
        raise ValueError(f"Document processing is not available for {file_type}")
    if backend == "manual":
        parser = MarkdownParser() if file_type == "text/markdown" else TextParser()
        chunker = StructureAwareChunker(
            target_tokens=target_tokens, max_tokens=max_tokens, token_counter=token_counter
        )
    elif backend == "langchain":
        parser = LangChainMarkdownParser() if file_type == "text/markdown" else LangChainTextParser()
        chunker = LangChainChunker(
            target_tokens=target_tokens, max_tokens=max_tokens, token_counter=token_counter
        )
    else:
        raise ValueError(f"Unknown document processing backend: {backend}")
    return DocumentProcessor(parser=parser, chunker=chunker)
