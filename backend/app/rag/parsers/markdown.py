import re

from app.rag.types import ParsedBlock, ParsedDocument

_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$")


class MarkdownParser:
    """Recognize ATX headings and blank-line-delimited paragraphs only."""

    def parse(self, text: str) -> ParsedDocument:
        blocks: list[ParsedBlock] = []
        headings: list[tuple[int, str]] = []
        paragraph: list[str] = []

        def section_path() -> tuple[str, ...]:
            return tuple(title for _, title in headings)

        def flush_paragraph() -> None:
            if paragraph:
                blocks.append(
                    ParsedBlock(
                        "\n".join(paragraph),
                        "paragraph",
                        len(blocks),
                        section_path=section_path(),
                    )
                )
                paragraph.clear()

        for line in text.splitlines():
            if not line.strip():
                flush_paragraph()
                continue

            match = _HEADING.match(line)
            if match:
                flush_paragraph()
                level = len(match.group(1))
                title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, title))
                blocks.append(
                    ParsedBlock(title, "heading", len(blocks), level, section_path())
                )
            else:
                paragraph.append(line.strip())

        flush_paragraph()
        return ParsedDocument(blocks)
