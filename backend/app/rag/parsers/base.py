from typing import Protocol, TypeVar

from app.rag.types import ChunkCandidate, ParsedDocument


SourceT = TypeVar("SourceT", contravariant=True)


class DocumentParser(Protocol[SourceT]):
    def parse(self, source: SourceT) -> ParsedDocument: ...


class DocumentChunker(Protocol):
    def chunk(self, document: ParsedDocument) -> list[ChunkCandidate]: ...
