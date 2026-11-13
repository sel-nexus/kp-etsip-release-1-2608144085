"""Exercise role HTTP contracts, audit failures and live JWT authorization."""
import asyncio
import pytest
from bson import ObjectId
from api.core.security import create_access_token
from api.core.policy import ROLE_MAXIMUM

@pytest.fixture
async def admin(db, app, identity):
    """Issue a real signed identity after persisting administrator assignment."""
    user, _ = identity
    await db.users.update_one({'_id': user['_id']}, {'$set': {'role': 'Administrator'}})
    return {'Authorization': 'Bearer ' + create_access_token(user['_id'], app.state.settings)}

@pytest.mark.parametrize('name', list(ROLE_MAXIMUM))
async def test_http_ensure_race_edit_idempotence_and_stale(client, db, admin, name):
    # Administrator must remain present to authenticate this ensure call.
    if name != 'Administrator': await db.roles.delete_one({'name': name})
    responses = await asyncio.gather(*(client.post('/api/roles', headers=admin, json={'name': name}) for _ in range(8)))
    assert all(row.status_code == 200 for row in responses)
    item = responses[0].json(); identifier = ObjectId(item['id'])
    assert all(row.json()['id'] == item['id'] for row in responses)
    assert set(item['permissions']) == ROLE_MAXIMUM[name]
    assert await db.roles.count_documents({'name': name}) == 1
    assert await db.audit_logs.count_documents({'entityId': identifier, 'action': 'create'}) == (0 if name == 'Administrator' else 1)
    permissions = ['administer'] if name == 'Administrator' else []
    edited = await client.put('/api/roles/'+item['id'], headers=admin, json={'permissions': permissions, 'expectedUpdatedAt': item['updatedAt']})
    assert edited.status_code == 200 and edited.json()['permissions'] == permissions
    before = await db.roles.find_one({'_id': identifier})
    ensured = await client.post('/api/roles', headers=admin, json={'name': name})
    assert ensured.status_code == 200 and ensured.json()['permissions'] == permissions
    assert await db.roles.find_one({'_id': identifier}) == before
    stale = await client.put('/api/roles/'+item['id'], headers=admin, json={'permissions': sorted(ROLE_MAXIMUM[name]), 'expectedUpdatedAt': item['updatedAt']})
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'CONFLICT'
    assert await db.roles.find_one({'_id': identifier}) == before
    listing = await client.get('/api/roles', headers=admin)
    assert listing.status_code == 200 and set(listing.json()) == {'items'}
    assert len(listing.json()['items']) == 6
    restored = await client.put('/api/roles/'+item['id'], headers=admin, json={'permissions': sorted(ROLE_MAXIMUM[name])})
    assert restored.status_code == 200
    assert set((await db.roles.find_one({'_id': identifier}))['permissions']) == ROLE_MAXIMUM[name]
    assert await db.audit_logs.count_documents({'entityId': identifier, 'action': 'permissionChange'}) == 2

@pytest.mark.parametrize('role', list(ROLE_MAXIMUM))
async def test_role_matrix_and_no_token(client, db, app, identity, role):
    user, _ = identity
    await db.users.update_one({'_id': user['_id']}, {'$set': {'role': role}})
    headers = {'Authorization': 'Bearer '+create_access_token(user['_id'], app.state.settings)}
    engineer = await db.roles.find_one({'name': 'Engineer'})
    before = await db.roles.find({}).sort('name', 1).to_list(None)
    for method, path, body in [('GET', '/api/roles', None), ('POST', '/api/roles', {'name': 'Engineer'}), ('PUT', '/api/roles/'+str(engineer['_id']), {'permissions': ['view']})]:
        response = await client.request(method, path, headers=headers, json=body)
        assert response.status_code == (200 if role == 'Administrator' else 403)
        assert (await client.request(method, path, json=body)).status_code == 401
    if role != 'Administrator':
        assert await db.roles.find({}).sort('name', 1).to_list(None) == before
        assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('body', [{}, {'name': 'Custom'}, {'name': ''}, {'name': 1}, {'name': {'$ne': None}}, {'name': 'Engineer', 'permissions': []}, {'name': 'Auditor', 'description': 'edit'}, {'name': 'x'*1000}])
async def test_invalid_ensure_rejects_without_changes(client, db, admin, body):
    before = await db.roles.find({}).sort('name', 1).to_list(None)
    response = await client.post('/api/roles', headers=admin, json=body)
    assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert await db.roles.find({}).sort('name', 1).to_list(None) == before
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('body', [{}, {'permissions': None}, {'permissions': 'view'}, {'permissions': {}}, {'permissions': [1]}, {'permissions': [True]}, {'permissions': ['unknown']}, {'permissions': ['view','view']}, {'permissions': ['view']*100}, {'permissions': [], 'name': 'Auditor'}, {'permissions': [], 'description': 'edit'}, {'permissions': [], 'expectedUpdatedAt': None}, {'permissions': [], 'expectedUpdatedAt': 123}, {'permissions': [], 'expectedUpdatedAt': 'bad'}, {'permissions': [], 'expectedUpdatedAt': '2026-01-01T00:00:00'}])
async def test_invalid_update_fields_reject(client, db, admin, body):
    row = await db.roles.find_one({'name': 'Engineer'})
    response = await client.put('/api/roles/'+str(row['_id']), headers=admin, json=body)
    assert response.status_code == 422
    assert await db.roles.find_one({'_id': row['_id']}) == row and await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('name', ['Executive','Portfolio Leader','Engineer','Auditor','Read Only'])
async def test_bound_expansion_returns_422(client, db, admin, name):
    row = await db.roles.find_one({'name': name})
    response = await client.put('/api/roles/'+str(row['_id']), headers=admin, json={'permissions': ['administer']})
    assert response.status_code == 422
    assert await db.roles.find_one({'_id': row['_id']}) == row and await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('identifier', ['bad', str(ObjectId())])
async def test_missing_and_no_custom_delete(client, admin, identifier):
    response = await client.put('/api/roles/'+identifier, headers=admin, json={'permissions': []})
    assert response.status_code == 404 and response.json()['error']['code'] == 'NOT_FOUND'
    assert (await client.delete('/api/roles/'+identifier, headers=admin)).status_code == 405

@pytest.mark.parametrize('method', ['GET','POST','PUT'])
async def test_queries_forbidden(client, db, admin, method):
    row = await db.roles.find_one({'name': 'Engineer'})
    path = '/api/roles' + ('/'+str(row['_id']) if method == 'PUT' else '')
    response = await client.request(method, path+'?unknown=1', headers=admin, json={'permissions': []} if method == 'PUT' else {'name': 'Engineer'} if method == 'POST' else None)
    assert response.status_code == 400
    assert await db.roles.find_one({'_id': row['_id']}) == row

@pytest.mark.parametrize('operation', ['ensure','update'])
async def test_audit_outage_reports_partial_write(client, db, admin, operation):
    """Have Mongo reject the audit write while retaining the committed role."""
    row = await db.roles.find_one({'name': 'Engineer'})
    if operation == 'ensure': await db.roles.delete_one({'_id': row['_id']})
    options = await db.audit_logs.options()
    await db.command('collMod', 'audit_logs', validator={'$jsonSchema': {'required': ['testOnlyAuditApproval']}}, validationLevel='strict', validationAction='error')
    try:
        response = await client.post('/api/roles', headers=admin, json={'name':'Engineer'}) if operation == 'ensure' else await client.put('/api/roles/'+str(row['_id']), headers=admin, json={'permissions': []})
    finally:
        await db.command('collMod', 'audit_logs', validator=options.get('validator', {}), validationLevel=options.get('validationLevel', 'strict'), validationAction=options.get('validationAction', 'error'))
    assert response.status_code == 503 and response.json()['error']['code'] == 'AUDIT_WRITE_FAILED'
    assert response.headers['X-Correlation-ID']
    stored = await db.roles.find_one({'name':'Engineer'})
    assert stored['permissions'] == (sorted(ROLE_MAXIMUM['Engineer']) if operation == 'ensure' else [])
    assert await db.audit_logs.count_documents({}) == 0

async def test_existing_token_loses_edit_on_next_request_and_restores(client, db, app, admin, identity):
    user, _ = identity
    second = {**user, '_id': ObjectId(), 'email': 'other@example.com', 'role': 'Engineer'}
    await db.users.insert_one(second)
    token = {'Authorization': 'Bearer '+create_access_token(second['_id'], app.state.settings)}
    role = await db.roles.find_one({'name':'Engineer'})
    # A nonexistent application normally reaches resource lookup (404).
    path = '/api/applications/'+str(ObjectId())
    assert (await client.put(path, headers=token, json={'qualityScore':80})).status_code == 404
    response = await client.put('/api/roles/'+str(role['_id']), headers=admin, json={'permissions':['view','export']})
    assert response.status_code == 200
    assert (await client.put(path, headers=token, json={'qualityScore':80})).status_code == 403
    assert (await client.get('/api/auth/me', headers=token)).status_code == 200
    assert (await client.put('/api/roles/'+str(role['_id']), headers=admin, json={'permissions':sorted(ROLE_MAXIMUM['Engineer'])})).status_code == 200
    assert (await client.put(path, headers=token, json={'qualityScore':80})).status_code == 404
    assert await db.applications.count_documents({}) == 0

async def test_admin_permission_reduction_and_password_gate(client, db, admin):
    row = await db.roles.find_one({'name':'Administrator'})
    await db.users.update_many({}, {'$set': {'mustChangePassword': True}})
    assert (await client.get('/api/roles',headers=admin)).status_code == 403
    await db.users.update_many({}, {'$set': {'mustChangePassword': False}})
    assert (await client.put('/api/roles/'+str(row['_id']), headers=admin, json={'permissions':['view']})).status_code == 200
    assert (await client.get('/api/roles',headers=admin)).status_code == 403
