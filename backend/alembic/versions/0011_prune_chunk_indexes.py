"""Remove vector indexes redundant for the current exact retrieval path.

Revision ID: 0011_prune_chunk_indexes
Revises: 0010_agent_runs
"""

from alembic import op

revision = "0011_prune_chunk_indexes"
down_revision = "0010_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_chunks_embedding_hnsw",
            table_name="chunks",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_chunks_document_version",
            table_name="chunks",
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_chunks_document_version",
            "chunks",
            ["document_id", "index_version"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_chunks_embedding_hnsw",
            "chunks",
            ["embedding"],
            postgresql_concurrently=True,
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
