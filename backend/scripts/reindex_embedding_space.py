"""Preview or enqueue tenant documents needing the configured embedding space."""

import argparse
import asyncio
import uuid

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.services.embedding_reindex import find_embedding_reindex_candidates
from app.services.errors import Conflict, NotFound
from app.services.index_jobs import enqueue_reindex


async def main(tenant_id: uuid.UUID, *, apply: bool, batch_size: int) -> None:
    settings = get_settings()
    space_id = settings.embedding_space_id
    scanned = queued = skipped = removed = 0
    cursor: uuid.UUID | None = None
    try:
        while True:
            async with SessionLocal() as db:
                batch = await find_embedding_reindex_candidates(
                    db,
                    tenant_id=tenant_id,
                    embedding_space_id=space_id,
                    after_document_id=cursor,
                    batch_size=batch_size,
                )
            if not batch:
                break
            for candidate in batch:
                cursor = candidate.document_id
                scanned += 1
                label = (
                    f"document={candidate.document_id} "
                    f"knowledge_base={candidate.knowledge_base_id} "
                    f"active_version={candidate.active_index_version} "
                    f"recorded_space={candidate.recorded_space_id or 'unknown'}"
                )
                if not apply:
                    print(f"WOULD_REINDEX {label}")
                    continue
                async with SessionLocal() as db:
                    try:
                        job = await enqueue_reindex(
                            db, candidate.document_id, settings, tenant_id=tenant_id
                        )
                    except Conflict:
                        skipped += 1
                        print(f"SKIPPED_ACTIVE_JOB {label}")
                    except NotFound:
                        removed += 1
                        print(f"SKIPPED_REMOVED {label}")
                    else:
                        queued += 1
                        print(f"QUEUED {label} job={job.id}")
        print(
            f"space={space_id} scanned={scanned} queued={queued} "
            f"skipped_active={skipped} skipped_removed={removed} "
            f"mode={'apply' if apply else 'preview'}"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--apply", action="store_true", help="Create jobs; default only previews"
    )
    arguments = parser.parse_args()
    if arguments.batch_size < 1:
        parser.error("--batch-size must be positive")
    asyncio.run(
        main(
            arguments.tenant_id, apply=arguments.apply, batch_size=arguments.batch_size
        )
    )
