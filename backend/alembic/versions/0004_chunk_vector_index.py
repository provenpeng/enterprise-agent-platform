"""Add HNSW cosine search index for chunk embeddings.

Revision ID: 0004_chunk_vector_index
Revises: 0003_document_index_jobs
"""

from alembic import op

revision = "0004_chunk_vector_index"
down_revision = "0003_document_index_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
