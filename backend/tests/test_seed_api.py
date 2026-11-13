"""Verify seed persistence, authentication and failures against real MongoDB."""
import asyncio
import secrets
from uuid import uuid4
import pytest
from bson import ObjectId
from httpx import AsyncClient, ASGITransport
from pymongo.errors import ServerSelectionTimeoutError, DuplicateKeyError
from api.core.config import Settings
from api.core.security import verify_password
from api.core.policy import ROLE_MAXIMUM
from api.domains.applications.schemas import Application
from api.main import create_app
from api.seed.runner import seed_database, run_seed


def seed_settings(app):
    """Use the fixture's database with generated credentials, never deployment passwords."""
    return app.state.settings.model_copy(update={
        'SEED_ADMIN_PASSWORD': __import__('pydantic').SecretStr(secrets.token_urlsafe(24)),
        'SEED_DEMO_PASSWORD': __import__('pydantic').SecretStr(secrets.token_urlsafe(24)),
    })


async def assert_inventory(db):
    """Re-query exact counts, BSON links and safe validated records."""
    assert [await db[name].count_documents({}) for name in ('roles', 'users', 'portfolios', 'applications')] == [6, 6, 3, 10]
    parents = {row['_id'] for row in await db.portfolios.find({}).to_list(None)}
    for row in await db.applications.find({}).to_list(None):
        Application.model_validate(row)
        assert isinstance(row['portfolioId'], ObjectId) and row['portfolioId'] in parents
    for row in await db.users.find({}).to_list(None):
        assert row['role'] in ROLE_MAXIMUM
        assert all(isinstance(value, ObjectId) and value in parents for value in row['portfolioAccess'])
        assert row['passwordHash'].startswith('$2')
    assert await db.portfolios.count_documents({'_applicationReservations.0': {'$exists': True}}) == 0


async def test_seed_twice_counts_links_hashes_and_unique_indexes(app, db, client):
    """Prove repeatability and uniqueness through actual database arbitration."""
    settings = seed_settings(app)
    await seed_database(db, settings)
    snapshot = await db.users.find({}).sort('email').to_list(None)
    await seed_database(db, settings)
    await assert_inventory(db)
    assert snapshot == await db.users.find({}).sort('email').to_list(None)
    for row in snapshot:
        password = settings.require_seed_passwords()[row['role'] != 'Administrator']
        assert row['passwordHash'] != password
        assert await verify_password(password, row['passwordHash'])
    for collection, key in [('roles','name'), ('users','email'), ('portfolios','name'), ('applications','name')]:
        indexes = await db[collection].index_information()
        assert any(index.get('unique') and index['key'] == [(key, 1)] for index in indexes.values())
        row = await db[collection].find_one({})
        row.pop('_id')
        with pytest.raises(DuplicateKeyError):
            await db[collection].insert_one(row)
    assert (await client.get('/api/health')).json() == {'status': 'ok'}


async def test_gate_change_password_and_edited_data_survive_reseed(app, db, client):
    """Unlock seeded admin once and never reset hashes, preferences, roles or inventory."""
    settings = seed_settings(app)
    await seed_database(db, settings)
    password = settings.require_seed_passwords()[0]
    response = await client.post('/api/auth/login', json={'email': 'admin@ketsip.local', 'password': password})
    assert response.status_code == 200
    assert 'passwordHash' not in response.text and password not in response.text
    assert response.json()['user']['mustChangePassword']
    headers = {'Authorization': 'Bearer ' + response.json()['token']}
    assert (await client.get('/api/applications', headers=headers)).status_code == 403
    assert (await client.post('/api/auth/change-password', headers=headers, json={'currentPassword': secrets.token_urlsafe(24), 'newPassword': secrets.token_urlsafe(24)})).status_code == 403
    assert (await db.users.find_one({'email': 'admin@ketsip.local'}))['mustChangePassword']
    replacement = secrets.token_urlsafe(24)
    changed = await client.post('/api/auth/change-password', headers=headers, json={'currentPassword': password, 'newPassword': replacement})
    assert changed.status_code == 200 and not changed.json()['mustChangePassword']
    await db.roles.update_one({'name': 'Engineer'}, {'$set': {'permissions': ['view']}})
    await db.applications.update_one({'name': 'Payment Gateway'}, {'$set': {'qualityScore': 11, 'description': 'Operator edited'}})
    await db.portfolios.update_one({'name': 'Payments'}, {'$set': {'ownerName': 'Operator edited'}})
    await db.users.update_one({'email': 'admin@ketsip.local'}, {'$set': {'defaultLandingPage': 'reports'}})
    old = await db.users.find_one({'email': 'admin@ketsip.local'})
    await seed_database(db, settings)
    assert await db.users.find_one({'email': 'admin@ketsip.local'}) == old
    assert await verify_password(replacement, old['passwordHash'])
    assert (await db.roles.find_one({'name':'Engineer'}))['permissions'] == ['view']
    assert (await db.applications.find_one({'name':'Payment Gateway'}))['qualityScore'] == 11
    assert (await db.portfolios.find_one({'name':'Payments'}))['ownerName'] == 'Operator edited'
    assert (await client.get('/api/applications', headers=headers)).status_code == 200
    assert (await client.post('/api/auth/login', json={'email':'admin@ketsip.local','password':replacement})).json()['user']['mustChangePassword'] is False


async def test_concurrent_seed_has_one_natural_key_winner(app, db):
    """Seed concurrently without duplicate identities, references or leaked pins."""
    settings = seed_settings(app)
    await asyncio.gather(*(seed_database(db, settings) for _ in range(3)))
    await assert_inventory(db)


async def test_invalid_seed_credentials_make_no_writes_and_block_startup(app, db):
    """Reject configuration before touching a collection or accepting requests."""
    settings = seed_settings(app).model_copy(update={'SEED_DEMO_PASSWORD': None})
    with pytest.raises(ValueError, match='SEED_DEMO_PASSWORD'):
        await seed_database(db, settings)
    assert [await db[name].count_documents({}) for name in ('roles','users','portfolios','applications')] == [0,0,0,0]
    application = create_app(settings.model_copy(update={'SEED_ON_STARTUP': True}))
    with pytest.raises(ValueError, match='SEED_DEMO_PASSWORD'):
        async with application.router.lifespan_context(application):
            pytest.fail('Invalid seed startup yielded')


async def test_startup_seed_reuses_lifespan_and_cli_reseeds_same_database(app):
    """Prove startup and CLI share the service and close their client lifecycles."""
    settings = seed_settings(app).model_copy(update={'SEED_ON_STARTUP': True, 'MONGODB_DB':'etsip_test_' + uuid4().hex})
    application = create_app(settings)
    try:
        async with application.router.lifespan_context(application):
            await assert_inventory(application.state.database)
            await run_seed(settings)
            await assert_inventory(application.state.database)
            async with AsyncClient(transport=ASGITransport(app=application), base_url='http://test') as http:
                assert (await http.get('/api/health')).status_code == 200
    finally:
        await app.state.mongo_client.drop_database(settings.MONGODB_DB)


async def test_unreachable_database_blocks_seed_startup_and_cli(app):
    """Require Mongo readiness, never fall back or silently yield on failure."""
    settings = seed_settings(app).model_copy(update={'MONGODB_URI':'mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=100', 'SEED_ON_STARTUP': True})
    with pytest.raises(ServerSelectionTimeoutError):
        await run_seed(settings)
    application = create_app(settings)
    with pytest.raises(ServerSelectionTimeoutError):
        async with application.router.lifespan_context(application):
            pytest.fail('Unreachable startup yielded')


async def test_parent_deletion_intent_blocks_new_seed_references(app, db):
    """Respect existing deployment deletion reservations and leave no orphan links."""
    settings = seed_settings(app)
    await seed_database(db, settings)
    await db.applications.delete_many({})
    await db.portfolios.update_one({'name':'Payments'}, {'$set': {'_applicationDeleting':True}})
    with pytest.raises(ValueError):
        await seed_database(db, settings)
    assert await db.applications.count_documents({}) == 0
    assert await db.portfolios.count_documents({'_applicationReservations.0': {'$exists':True}}) == 0
