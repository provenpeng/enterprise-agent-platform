from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from app.rag.processing import create_document_processor


def make_pdf(*pages: str) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output)
    for content in pages:
        if content:
            pdf.drawString(72, 720, content)
        pdf.showPage()
    pdf.save()
    return output.getvalue()


@pytest.mark.parametrize("backend", ["manual", "langchain"])
def test_pdf_pages_keep_source_page_and_do_not_merge(backend: str) -> None:
    processor = create_document_processor(
        backend=backend,
        file_type="application/pdf",
        target_tokens=50,
        max_tokens=60,
        token_counter=len,
    )
    source = make_pdf("Refunds require approval.", "Final sale orders are excluded.")

    parsed = processor.parse(source)
    chunks = processor.process(source)

    assert [block.page_number for block in parsed.blocks] == [1, 2]
    assert [chunk.page_number for chunk in chunks] == [1, 2]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert "Refunds require approval." in chunks[0].content
    assert "Final sale orders are excluded." in chunks[1].content


@pytest.mark.parametrize("backend", ["manual", "langchain"])
def test_pdf_without_extractable_text_fails_explicitly(backend: str) -> None:
    processor = create_document_processor(
        backend=backend,
        file_type="application/pdf",
        target_tokens=50,
        max_tokens=60,
        token_counter=len,
    )

    with pytest.raises(ValueError, match="no extractable text"):
        processor.process(make_pdf(""))


def test_invalid_pdf_fails_explicitly() -> None:
    processor = create_document_processor(
        backend="manual",
        file_type="application/pdf",
        target_tokens=50,
        max_tokens=60,
        token_counter=len,
    )

    with pytest.raises(ValueError, match="Invalid PDF"):
        processor.process(b"not a PDF")


def test_password_protected_pdf_fails_explicitly() -> None:
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(BytesIO(make_pdf("Private rules."))))
    writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    processor = create_document_processor(
        backend="langchain",
        file_type="application/pdf",
        target_tokens=50,
        max_tokens=60,
        token_counter=len,
    )

    with pytest.raises(ValueError, match="Password-protected"):
        processor.process(output.getvalue())
