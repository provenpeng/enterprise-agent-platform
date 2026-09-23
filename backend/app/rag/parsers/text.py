from app.rag.types import ParsedBlock, ParsedDocument


class TextParser:
    """Group consecutive nonblank lines into paragraphs."""

    def parse(self, text: str) -> ParsedDocument:
        blocks: list[ParsedBlock] = []
        paragraph: list[str] = []

        def flush_paragraph() -> None:
            if paragraph:
                blocks.append(ParsedBlock("\n".join(paragraph), "paragraph", len(blocks)))
                paragraph.clear()

        for line in text.splitlines():
            if line.strip():
                paragraph.append(line.strip())
            else:
                flush_paragraph()

        flush_paragraph()
        return ParsedDocument(blocks)
