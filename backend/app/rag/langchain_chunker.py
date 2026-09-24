"""LangChain chunker that preserves the project's source block metadata."""

from collections.abc import Callable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.types import ChunkCandidate, ParsedDocument


class LangChainChunker:
    def __init__(
        self, *, target_tokens: int, max_tokens: int, token_counter: Callable[[str], int]
    ) -> None:
        if not 0 < target_tokens <= max_tokens:
            raise ValueError("Expected 0 < target_tokens <= max_tokens")
        self.max_tokens = max_tokens
        self.token_counter = token_counter
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=target_tokens,
            chunk_overlap=0,
            length_function=token_counter,
            separators=["\n\n", "\n", "。", "！", "？", ". ", " ", ""],
            keep_separator="end",
        )

    def chunk(self, document: ParsedDocument) -> list[ChunkCandidate]:
        source_documents = [
            Document(
                page_content=block.text,
                metadata={"section_path": block.section_path, "block_order": block.order},
            )
            for block in document.blocks
            if block.block_type == "paragraph" and block.text.strip()
        ]
        chunks: list[ChunkCandidate] = []
        for part in self._splitter.split_documents(source_documents):
            count = self.token_counter(part.page_content)
            if count < 0 or count > self.max_tokens:
                raise ValueError("Chunk token count is outside configured limits")
            order = part.metadata["block_order"]
            chunks.append(
                ChunkCandidate(
                    content=part.page_content,
                    chunk_index=len(chunks),
                    section_path=part.metadata["section_path"],
                    token_count=count,
                    block_start=order,
                    block_end=order,
                )
            )
        return chunks
