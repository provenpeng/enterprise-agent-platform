from typing import Protocol

from app.rag.types import ParsedDocument


class DocumentParser(Protocol):
    def parse(self, text: str) -> ParsedDocument: ...
