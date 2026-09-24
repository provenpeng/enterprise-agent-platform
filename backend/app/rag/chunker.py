import re
from collections.abc import Callable

from app.rag.types import ChunkCandidate, ParsedBlock, ParsedDocument


_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s*")


class StructureAwareChunker:
    def __init__(
        self, *, target_tokens: int, max_tokens: int, token_counter: Callable[[str], int]
    ) -> None:
        if not 0 < target_tokens <= max_tokens:
            raise ValueError("Expected 0 < target_tokens <= max_tokens")
        self.target_tokens = target_tokens
        self.max_tokens = max_tokens
        self.token_counter = token_counter

    def _count(self, text: str) -> int:
        count = self.token_counter(text)
        if count < 0:
            raise ValueError("token_counter must return a non-negative count")
        return count

    def _append_fits(self, current: str, part: str, separator: str) -> bool:
        # Prefer the packing closer to the soft target, subject to the hard maximum.
        combined = f"{current}{separator}{part}"
        combined_count = self._count(combined)
        return combined_count <= self.max_tokens and (
            abs(combined_count - self.target_tokens)
            <= abs(self._count(current) - self.target_tokens)
        )

    def _split_long_word(self, word: str) -> list[str]:
        parts: list[str] = []
        current = ""
        for character in word:
            if self._count(character) > self.max_tokens:
                raise ValueError("A single character exceeds max_tokens")
            if current and not self._append_fits(current, character, ""):
                parts.append(current)
                current = ""
            current += character
        if current:
            parts.append(current)
        return parts

    def _split_words(self, sentence: str) -> list[str]:
        parts: list[str] = []
        current = ""
        for word in sentence.split():
            if self._count(word) > self.max_tokens:
                if current:
                    parts.append(current)
                    current = ""
                parts.extend(self._split_long_word(word))
                continue
            if current and not self._append_fits(current, word, " "):
                parts.append(current)
                current = ""
            current = f"{current} {word}" if current else word
        if current:
            parts.append(current)
        return parts

    def _split_paragraph(self, text: str) -> list[str]:
        parts: list[str] = []
        current = ""
        for sentence in filter(None, (part.strip() for part in _SENTENCE_END.split(text))):
            if self._count(sentence) > self.max_tokens:
                if current:
                    parts.append(current)
                    current = ""
                parts.extend(self._split_words(sentence))
                continue
            if current and not self._append_fits(current, sentence, " "):
                parts.append(current)
                current = ""
            current = f"{current} {sentence}" if current else sentence
        if current:
            parts.append(current)
        return parts

    def chunk(self, document: ParsedDocument) -> list[ChunkCandidate]:
        chunks: list[ChunkCandidate] = []
        pending: list[ParsedBlock] = []

        def emit(
            content: str,
            section_path: tuple[str, ...],
            start: int,
            end: int,
            page_number: int | None,
        ) -> None:
            chunks.append(
                ChunkCandidate(
                    content=content,
                    chunk_index=len(chunks),
                    section_path=section_path,
                    token_count=self._count(content),
                    block_start=start,
                    block_end=end,
                    page_number=page_number,
                )
            )

        def flush() -> None:
            if pending:
                emit(
                    "\n\n".join(block.text for block in pending),
                    pending[0].section_path,
                    pending[0].order,
                    pending[-1].order,
                    pending[0].page_number,
                )
                pending.clear()

        for block in document.blocks:
            if block.block_type == "heading":
                flush()
                continue
            if block.block_type != "paragraph" or not block.text.strip():
                continue

            if pending and (
                pending[0].section_path != block.section_path
                or pending[0].page_number != block.page_number
            ):
                flush()
            if self._count(block.text) > self.max_tokens:
                flush()
                for part in self._split_paragraph(block.text):
                    emit(part, block.section_path, block.order, block.order, block.page_number)
                continue

            if pending and not self._append_fits(
                "\n\n".join(item.text for item in pending), block.text, "\n\n"
            ):
                flush()
            pending.append(block)

        flush()
        return chunks
