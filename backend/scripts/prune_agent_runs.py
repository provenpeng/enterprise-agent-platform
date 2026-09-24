"""Delete diagnostic traces older than the explicit retention window."""

import argparse
import asyncio

from app.agent.retention import prune_agent_runs
from app.db.session import SessionLocal


async def main(days: int) -> None:
    async with SessionLocal() as db:
        count = await prune_agent_runs(db, days=days)
    print(f"Deleted {count} Agent runs older than {days} days")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prune old Agent run traces")
    parser.add_argument("--days", type=int, default=30)
    arguments = parser.parse_args()
    asyncio.run(main(arguments.days))
