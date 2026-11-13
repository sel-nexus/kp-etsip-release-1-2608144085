"""Run insert-only demonstration seeding through existing domain repositories."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from api.core.config import Settings
from api.core.policy import ROLE_MAXIMUM, Scope, validate_permissions
from api.core.security import hash_password
from api.domains.roles.repository import RoleRepository
from api.domains.roles.service import DESCRIPTIONS
from api.domains.users.repository import UserRepository
from api.domains.users.schemas import UserCreate, User
from api.domains.portfolios.repository import PortfolioRepository
from api.domains.portfolios.schemas import PortfolioCreate
from api.domains.applications.repository import ApplicationRepository
from api.domains.applications.schemas import ApplicationCreate, Application
from api.migrations.indexes import create_indexes
from api.seed.data import PORTFOLIOS, APPLICATIONS, USERS, application_payload


async def seed_database(database: AsyncDatabase, settings: Settings) -> None:
    """Ensure baseline records without resetting permissions, passwords or inventory.

    Notes:
        Call after index initialization. Confirmed writes release parent pins;
        ambiguous database failures retain conservative pins for reconciliation.
        This additive operation is resumable, not a multi-document transaction.
    """
    admin_password, demo_password = settings.require_seed_passwords()
    now = datetime.now(timezone.utc)
    timestamps = {'createdAt': now, 'updatedAt': now}
    roles = RoleRepository(database)
    portfolios = PortfolioRepository(database)
    applications = ApplicationRepository(database)
    users = UserRepository(database)
    for name, permissions in ROLE_MAXIMUM.items():
        row, _ = await roles.ensure(dict(name=name, description=DESCRIPTIONS[name], permissions=sorted(permissions), **timestamps))
        validate_permissions(row['name'], row['permissions'])
    parents = []
    for payload in PORTFOLIOS:
        row = await portfolios.seed_ensure(dict(**PortfolioCreate.model_validate(payload).model_dump(), **timestamps))
        if not isinstance(row['_id'], ObjectId):
            raise ValueError('Seed parent must have a BSON identifier')
        parents.append(row['_id'])
    for role, email, name, positions in USERS:
        password = admin_password if role == 'Administrator' else demo_password
        request = UserCreate(name=name, email=f'{email}@ketsip.local', password=password, role=role,
                             portfolioAccess=[str(parents[index]) for index in positions], status='Active')
        identifiers = [ObjectId(value) for value in request.portfolioAccess]
        if not await users.role_exists(role) or not await users.portfolios_exist(identifiers):
            raise ValueError('Seed user references are unavailable')
        password_hash = await hash_password(password)
        token = 'seed-user-' + uuid4().hex
        reserved = []
        for identifier in identifiers:
            if not await users.reserve(identifier, token):
                for pinned in reserved:
                    await users.release(pinned, token)
                raise ValueError('Seed parent is being deleted')
            reserved.append(identifier)
        document = request.model_dump(exclude={'password'})
        document.update(portfolioAccess=identifiers, passwordHash=password_hash,
                        authSource='local', lastLogin=None, mustChangePassword=role == 'Administrator',
                        defaultLandingPage=None, **timestamps)
        row = await users.seed_ensure(document)
        for identifier in reserved:
            await users.release(identifier, token)
        User.model_validate(row)
        if row['role'] not in ROLE_MAXIMUM or not all(isinstance(value, ObjectId) for value in row['portfolioAccess']) or not await users.portfolios_exist(row['portfolioAccess']):
            raise ValueError('Existing seed user has invalid references')
    for payload in APPLICATIONS:
        parent = parents[payload[1]]
        request = ApplicationCreate.model_validate(application_payload(payload, str(parent)))
        token = 'seed-app-' + uuid4().hex
        if not await applications.reserve(Scope(None), parent, token):
            raise ValueError('Seed parent is being deleted')
        document = request.model_dump(mode='json')
        document.update(portfolioId=parent, **timestamps)
        row = await applications.seed_ensure(document)
        await applications.release(parent, token)
        Application.model_validate(row)
        if not isinstance(row['portfolioId'], ObjectId) or await applications.portfolio(Scope(None), row['portfolioId']) is None:
            raise ValueError('Existing seed application has invalid references')


async def run_seed(settings: Settings | None = None) -> None:
    """Own one CLI client, require readiness and indexes, and always close it."""
    configuration = settings or Settings()
    configuration.require_seed_passwords()
    client = AsyncMongoClient(configuration.MONGODB_URI, tz_aware=True)
    try:
        await client.admin.command('ping')
        database = client.get_database(configuration.MONGODB_DB)
        await create_indexes(database)
        await seed_database(database, configuration)
    finally:
        await client.close()


if __name__ == '__main__':
    # Do not print validation input, connection strings or credentials on CLI failure.
    try:
        asyncio.run(run_seed())
    except Exception:
        raise SystemExit('Seed failed; check configuration, database readiness and stored references') from None
