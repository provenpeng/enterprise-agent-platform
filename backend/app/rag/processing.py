"""Stable entry point for interchangeable document processing implementations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from app.rag.chunker import StructureAwareChunker
from app.rag.langchain_chunker import LangChainChunker
from app.rag.parsers.base import DocumentChunker, DocumentParser
from app.rag.parsers.langchain import LangChainMarkdownParser, LangChainTextParser
from app.rag.parsers.markdown import MarkdownParser
from app.rag.parsers.pdf import PdfParser
from app.rag.parsers.text import TextParser
from app.rag.types import ChunkCandidate, ParsedDocument

ProcessingBackend = Literal["manual", "langchain"]
PROCESSING_VERSION = "1"
SourceT = TypeVar("SourceT")


@dataclass(frozen=True)
class DocumentProcessor(Generic[SourceT]):
    parser: DocumentParser[SourceT]
    chunker: DocumentChunker

    def parse(self, source: SourceT) -> ParsedDocument:
        return self.parser.parse(source)

    def process(self, source: SourceT) -> list[ChunkCandidate]:
        return self.chunker.chunk(self.parse(source))


def create_document_processor(
    *,
    backend: ProcessingBackend,
    file_type: str,
    target_tokens: int,
    max_tokens: int,
    token_counter: Callable[[str], int],
) -> DocumentProcessor[str] | DocumentProcessor[bytes]:
    if file_type not in {"text/plain", "text/markdown", "application/pdf"}:
        raise ValueError(f"Document processing is not available for {file_type}")
    if backend == "manual":
        text_parser = MarkdownParser() if file_type == "text/markdown" else TextParser()
        chunker = StructureAwareChunker(
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            token_counter=token_counter,
        )
    elif backend == "langchain":
        text_parser = (
            LangChainMarkdownParser()
            if file_type == "text/markdown"
            else LangChainTextParser()
        )
        chunker = LangChainChunker(
            target_tokens=target_tokens,
            max_tokens=max_tokens,
            token_counter=token_counter,
        )
    else:
        raise ValueError(f"Unknown document processing backend: {backend}")
    parser = PdfParser(text_parser) if file_type == "application/pdf" else text_parser
    return DocumentProcessor(parser=parser, chunker=chunker)
