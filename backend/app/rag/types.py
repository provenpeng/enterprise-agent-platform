from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    block_type: Literal["heading", "paragraph"]
    order: int
    heading_level: int | None = None
    section_path: tuple[str, ...] = ()


@dataclass
class ParsedDocument:
    blocks: list[ParsedBlock]


@dataclass(frozen=True)
class ChunkCandidate:
    content: str
    chunk_index: int
    section_path: tuple[str, ...]
    token_count: int
    block_start: int | None
    block_end: int | None
