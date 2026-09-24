from sqlalchemy import UniqueConstraint

from app.db.base import Base
from app.models import Chunk, Document, DocumentStatus, IndexJob


def test_domain_tables_and_cascading_foreign_keys() -> None:
    assert set(Base.metadata.tables) == {
        "tenants",
        "knowledge_bases",
        "documents",
        "chunks",
        "document_index_jobs",
        "demo_orders",
        "demo_refund_attempts",
    }
    assert next(iter(Document.__table__.foreign_keys)).ondelete == "CASCADE"
    assert next(iter(Chunk.__table__.foreign_keys)).ondelete == "CASCADE"
    assert "embedding" in Chunk.__table__.columns
    assert next(iter(IndexJob.__table__.foreign_keys)).ondelete == "CASCADE"
    assert "tenant_id" not in Document.__table__.columns


def test_chunk_versions_are_unique_per_document() -> None:
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns}
        == {"document_id", "index_version", "chunk_index"}
        for constraint in Chunk.__table__.constraints
    )


def test_failed_reindex_does_not_clear_active_version() -> None:
    document = Document(
        filename="rules.pdf",
        file_type="application/pdf",
        storage_uri="file:///rules.pdf",
        checksum="example-checksum",
        status=DocumentStatus.READY,
        active_index_version=1,
    )
    document.status = DocumentStatus.FAILED

    assert document.status == DocumentStatus.FAILED
    assert document.active_index_version == 1


def test_active_version_can_be_null_for_new_document() -> None:
    assert Document().active_index_version is None
