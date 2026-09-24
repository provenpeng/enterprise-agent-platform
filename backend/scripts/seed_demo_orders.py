"""Load synthetic orders for one provisioned tenant, with no network calls."""

import argparse
import asyncio
import uuid

from app.business.demo_seed import seed_demo_orders
from app.db.session import SessionLocal


async def main(tenant_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        count = await seed_demo_orders(db, tenant_id)
    print(f"Created {count} demo orders for tenant {tenant_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed fictitious demo orders")
    parser.add_argument("--tenant-id", required=True, type=uuid.UUID)
    arguments = parser.parse_args()
    asyncio.run(main(arguments.tenant_id))
