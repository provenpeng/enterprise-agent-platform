from typing import Protocol

from app.rag.types import ChunkCandidate, ParsedDocument


class DocumentParser(Protocol):
    def parse(self, text: str) -> ParsedDocument: ...


class DocumentChunker(Protocol):
    def chunk(self, document: ParsedDocument) -> list[ChunkCandidate]: ...
