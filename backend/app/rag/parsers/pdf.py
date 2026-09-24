"""Extract page text from PDF and delegate text structure to the selected backend."""

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.rag.parsers.base import DocumentParser
from app.rag.types import ParsedBlock, ParsedDocument


class PdfParser:
    def __init__(self, page_parser: DocumentParser[str]) -> None:
        self.page_parser = page_parser

    def parse(self, source: bytes) -> ParsedDocument:
        try:
            pdf = PdfReader(BytesIO(source), strict=False)
            if pdf.is_encrypted:
                raise ValueError("Password-protected PDF documents are not supported")

            blocks: list[ParsedBlock] = []
            for page_index, page in enumerate(pdf.pages):
                parsed = self.page_parser.parse(page.extract_text() or "")
                for block in parsed.blocks:
                    blocks.append(
                        ParsedBlock(
                            text=block.text,
                            block_type=block.block_type,
                            order=len(blocks),
                            heading_level=block.heading_level,
                            section_path=block.section_path,
                            page_number=page_index + 1,
                        )
                    )
        except (PdfReadError, OSError) as exc:
            raise ValueError("Invalid PDF document") from exc

        if not blocks:
            raise ValueError("PDF has no extractable text")
        return ParsedDocument(blocks)
