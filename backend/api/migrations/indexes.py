"""Establish auth indexes idempotently without destructive index replacement."""
import asyncio
from pymongo.asynchronous.database import AsyncDatabase
from pymongo import AsyncMongoClient
from api.core.config import Settings

async def create_indexes(database: AsyncDatabase) -> None:
    """Block initialization if required unique or audit indexes cannot be built."""
    await database.users.create_index('email', unique=True)
    await database.roles.create_index('name', unique=True)
    await database.portfolios.create_index('name', unique=True)
    await database.portfolios.create_index([('status', 1), ('productArea', 1)])
    await database.applications.create_index('name', unique=True)
    await database.applications.create_index([('portfolioId', 1), ('lifecycleStatus', 1)])
    await database.applications.create_index([('portfolioId', 1), ('criticality', 1), ('riskLevel', 1)])
    await database.applications.create_index([('portfolioId', 1), ('productArea', 1)])
    await database.audit_logs.create_index([('timestamp', -1)])
    await database.audit_logs.create_index([('userId', 1), ('timestamp', -1)])
    await database.audit_logs.create_index([('action', 1), ('timestamp', -1)])
async def migrate() -> None:
    """Run the same auth migration explicitly against configured Mongo."""
    settings = Settings()
    client = AsyncMongoClient(settings.MONGODB_URI, tz_aware=True)
    try:
        await create_indexes(client.get_database(settings.MONGODB_DB))
    finally:
        await client.close()
if __name__ == '__main__':
    asyncio.run(migrate())
