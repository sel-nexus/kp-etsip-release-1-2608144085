"""Own one async Mongo client for the complete application lifespan."""
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI
from pymongo import AsyncMongoClient
from api.core.config import Settings
from api.migrations.indexes import create_indexes

@asynccontextmanager
async def database_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize readiness and always await closure, including startup failures."""
    settings = app.state.settings or Settings()
    app.state.settings = settings
    client = AsyncMongoClient(settings.MONGODB_URI, tz_aware=True)
    app.state.mongo_client = client
    app.state.database = client.get_database(settings.MONGODB_DB)
    try:
        await client.admin.command('ping')
        await create_indexes(app.state.database)
        yield
    finally:
        await client.close()
