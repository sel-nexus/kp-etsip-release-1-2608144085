"""Provide disposable real Mongo databases and generated test-only credentials."""
import secrets
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from bson import ObjectId
from httpx import AsyncClient, ASGITransport
from api.core.config import Settings
from api.core.security import hash_password
from api.core.policy import ROLE_MAXIMUM
from api.main import create_app

@pytest.fixture
async def app():
    """Run the real lifespan and destroy only this fixture's unique database."""
    settings = Settings(MONGODB_DB='etsip_test_' + uuid4().hex, JWT_SECRET=secrets.token_urlsafe(48))
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application
        await application.state.mongo_client.drop_database(settings.MONGODB_DB)
@pytest.fixture
async def db(app):
    """Expose the same real pooled database used by HTTP calls."""
    return app.state.database
@pytest.fixture
async def client(app):
    """Exercise real endpoints without substituting persistence."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as http:
        yield http
@pytest.fixture
async def identity(db):
    """Persist an explicitly fake engineer using generated credentials."""
    now = datetime.now(timezone.utc)
    for role, permissions in ROLE_MAXIMUM.items():
        await db.roles.insert_one({'name': role, 'permissions': sorted(permissions), 'description': role, 'createdAt': now, 'updatedAt': now})
    password = secrets.token_urlsafe(24)
    user = {'_id': ObjectId(), 'name': 'Test Engineer', 'email': 'engineer@example.com', 'passwordHash': await hash_password(password), 'role': 'Engineer', 'portfolioAccess': [ObjectId()], 'status': 'Active', 'mustChangePassword': False, 'defaultLandingPage': None, 'authSource': 'local', 'managerName': None, 'vendorIndicator': False, 'lastLogin': None, 'createdAt': now, 'updatedAt': now}
    await db.users.insert_one(user)
    return user, password
