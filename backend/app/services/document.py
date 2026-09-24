import asyncio
import codecs
import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.services.index_jobs import new_index_job
from app.services.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    PayloadTooLarge,
    UnsupportedMedia,
)


logger = logging.getLogger(__name__)
READ_SIZE = 1024 * 1024
FILE_TYPES = {
    ".pdf": ("application/pdf", {"application/pdf"}),
    ".md": ("text/markdown", {"text/markdown", "text/plain", "text/x-markdown"}),
    ".txt": ("text/plain", {"text/plain"}),
}


class UploadSource(Protocol):
    filename: str | None
    content_type: str | None
    file: BinaryIO

    async def read(self, size: int = -1) -> bytes: ...
    async def seek(self, offset: int) -> None: ...


async def _inspect_upload(
    upload: UploadSource, max_size: int
) -> tuple[str, str, str, str]:
    filename = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or "\x00" in filename or len(filename) > 255:
        raise InvalidInput("Invalid filename")

    extension = Path(filename).suffix.lower()
    if extension not in FILE_TYPES:
        raise UnsupportedMedia("Unsupported file extension")

    file_type, allowed_mime_types = FILE_TYPES[extension]
    declared_mime = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if declared_mime not in allowed_mime_types:
        raise UnsupportedMedia("Unsupported file MIME type")

    checksum = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8")() if extension != ".pdf" else None
    size = 0
    first_chunk = True
    while chunk := await upload.read(READ_SIZE):
        size += len(chunk)
        if size > max_size:
            raise PayloadTooLarge("File is too large")
        if first_chunk and extension == ".pdf" and not chunk.startswith(b"%PDF-"):
            raise UnsupportedMedia("Invalid PDF header")
        first_chunk = False
        if decoder is not None:
            if b"\x00" in chunk:
                raise UnsupportedMedia("Invalid text file")
            try:
                decoder.decode(chunk)
            except UnicodeDecodeError as exc:
                raise UnsupportedMedia("Text must be UTF-8") from exc
        checksum.update(chunk)

    if size == 0:
        raise InvalidInput("File is empty")
    if decoder is not None:
        try:
            decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise UnsupportedMedia("Text must be UTF-8") from exc

    await upload.seek(0)
    return filename, extension, file_type, checksum.hexdigest()


def _save_original(source: BinaryIO, destination: Path, expected_checksum: str) -> None:
    temporary = destination.with_name(destination.name + ".part")
    checksum = hashlib.sha256()
    with temporary.open("xb") as target:
        while chunk := source.read(READ_SIZE):
            target.write(chunk)
            checksum.update(chunk)
        if checksum.hexdigest() != expected_checksum:
            raise OSError("Upload changed while saving")
        target.flush()
        os.fsync(target.fileno())
    temporary.replace(destination)


def _remove_original(destination: Path) -> None:
    destination.unlink(missing_ok=True)
    destination.with_name(destination.name + ".part").unlink(missing_ok=True)
    for directory in (destination.parent, destination.parent.parent):
        try:
            directory.rmdir()
        except OSError:
            break


async def upload_document(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    upload: UploadSource,
    settings: Settings,
) -> Document:
    knowledge_base = await db.scalar(
        select(KnowledgeBase.id).where(KnowledgeBase.id == knowledge_base_id)
    )
    await db.rollback()
    if knowledge_base is None:
        raise NotFound("Knowledge base not found")

    filename, extension, file_type, checksum = await _inspect_upload(
        upload, settings.max_upload_size_bytes
    )
    duplicate = await db.scalar(
        select(Document.id).where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.checksum == checksum,
        )
    )
    await db.rollback()
    if duplicate is not None:
        raise Conflict("Document with the same checksum already exists")

    document_id = uuid.uuid4()
    storage_key = f"{knowledge_base_id}/{document_id}/original{extension}"
    destination = settings.upload_dir.resolve() / storage_key
    document = Document(
        id=document_id,
        knowledge_base_id=knowledge_base_id,
        filename=filename,
        file_type=file_type,
        storage_uri=storage_key,
        checksum=checksum,
        status=DocumentStatus.UPLOADED,
        active_index_version=None,
    )
    index_job = new_index_job(document_id, 1, settings)

    directory_created = False
    committed = False
    try:
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=False)
        directory_created = True
        await asyncio.to_thread(_save_original, upload.file, destination, checksum)
        db.add(document)
        db.add(index_job)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            try:
                duplicate = await db.scalar(
                    select(Document.id).where(
                        Document.knowledge_base_id == knowledge_base_id,
                        Document.checksum == checksum,
                    )
                )
            finally:
                await db.rollback()
            if duplicate is not None:
                raise Conflict(
                    "Document with the same checksum already exists"
                ) from exc
            raise
        except Exception:
            await db.rollback()
            raise
        committed = True
        return document
    finally:
        if directory_created and not committed:
            try:
                await asyncio.to_thread(_remove_original, destination)
            except OSError:
                logger.exception("Could not remove failed upload: %s", destination)
