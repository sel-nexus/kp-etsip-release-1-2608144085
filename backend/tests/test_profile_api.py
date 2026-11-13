"""Exercise approved profile routes and first-password gating using real Mongo HTTP."""
import pytest
from api.core.security import create_access_token, verify_password

@pytest.fixture
async def headers(app, identity):
    """Issue a real signed subject token for profile requests."""
    return {'Authorization': 'Bearer ' + create_access_token(identity[0]['_id'], app.state.settings)}

async def test_first_login_gate_change_and_preference_persistence(client, db, identity, headers):
    user, password = identity
    await db.users.update_one({'_id': user['_id']}, {'$set': {'role': 'Administrator', 'mustChangePassword': True}})
    assert (await client.get('/api/auth/me', headers=headers)).json()['mustChangePassword'] is True
    assert (await client.post('/api/auth/logout', headers=headers)).status_code == 200
    denied = await client.put('/api/auth/preferences', headers=headers, json={'defaultLandingPage': 'profile'})
    assert denied.status_code == 403 and denied.json()['error']['code'] == 'PASSWORD_CHANGE_REQUIRED'
    before = await db.users.find_one({'_id': user['_id']})
    bad = await client.post('/api/auth/change-password', headers=headers, json={'currentPassword': 'wrong', 'newPassword': 'x'})
    assert bad.status_code == 403 and bad.json()['error']['code'] == 'FORBIDDEN'
    assert await db.users.find_one({'_id': user['_id']}) == before
    changed = await client.post('/api/auth/change-password', headers=headers, json={'currentPassword': password, 'newPassword': 'x'})
    assert changed.status_code == 200
    assert changed.json()['mustChangePassword'] is False
    assert set(changed.json()) == {'id','name','email','role','portfolioAccess','status','defaultLandingPage','mustChangePassword'}
    assert password not in changed.text and 'passwordHash' not in changed.text
    stored = await db.users.find_one({'_id': user['_id']})
    assert await verify_password('x', stored['passwordHash']) and not stored['mustChangePassword']
    saved = await client.put('/api/auth/preferences', headers=headers, json={'defaultLandingPage': 'roles'})
    assert saved.status_code == 200 and saved.json()['defaultLandingPage'] == 'roles'
    assert (await client.get('/api/auth/me', headers=headers)).json() == saved.json()
    assert (await db.users.find_one({'_id': user['_id']}))['defaultLandingPage'] == 'roles'
    old = await client.post('/api/auth/login', json={'email': user['email'], 'password': password})
    assert old.status_code == 401
    new = await client.post('/api/auth/login', json={'email': user['email'], 'password': 'x'})
    assert new.status_code == 200 and new.json()['user']['defaultLandingPage'] == 'roles'

@pytest.mark.parametrize('payload', [
    {}, {'currentPassword':'private'}, {'newPassword':'private'},
    {'currentPassword':'','newPassword':'private'}, {'currentPassword':'private','newPassword':''},
    {'currentPassword':123,'newPassword':'private'}, {'currentPassword':'private','newPassword':{'$ne':None}},
    {'currentPassword':'private','newPassword':'é'*37}, {'currentPassword':'a'*73,'newPassword':'private'},
    {'currentPassword':'private','newPassword':'a\x00b'}, {'currentPassword':'private','newPassword':'private','role':'Administrator'},
])
async def test_password_schema_rejects_without_echo_or_writes(client, db, identity, headers, payload):
    before = await db.users.find_one({'_id': identity[0]['_id']})
    response = await client.post('/api/auth/change-password', headers=headers, json=payload)
    assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert 'private' not in response.text
    assert await db.users.find_one({'_id': identity[0]['_id']}) == before
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('payload', [{}, {'defaultLandingPage':None}, {'defaultLandingPage':1}, {'defaultLandingPage':{'$ne':None}}, {'defaultLandingPage':'/profile'}, {'defaultLandingPage':'future'}, {'defaultLandingPage':'profile','userId':'other'}])
async def test_preference_schema_rejects_invalid_keys(client, db, identity, headers, payload):
    before = await db.users.find_one({'_id': identity[0]['_id']})
    response = await client.put('/api/auth/preferences', headers=headers, json=payload)
    assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert await db.users.find_one({'_id': identity[0]['_id']}) == before
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('method,path,payload', [('post','/api/auth/change-password',{'currentPassword':'x','newPassword':'y'}), ('put','/api/auth/preferences',{'defaultLandingPage':'profile'})])
@pytest.mark.parametrize('case', ['absent','invalid','inactive','missing'])
async def test_profile_authentication_boundaries(client, db, identity, headers, method, path, payload, case):
    if case == 'absent': headers = {}
    elif case == 'invalid': headers = {'Authorization':'Bearer invalid'}
    elif case == 'inactive': await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'status':'Inactive'}})
    else: await db.users.delete_one({'_id':identity[0]['_id']})
    response = await getattr(client, method)(path, headers=headers, json=payload)
    assert response.status_code == 401 and response.json()['error']['code'] == 'UNAUTHENTICATED'
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('destination', ['users','roles','audit'])
async def test_preference_permission_denials_have_no_state_change(client, db, identity, headers, destination):
    before = await db.users.find_one({'_id':identity[0]['_id']})
    response = await client.put('/api/auth/preferences', headers=headers, json={'defaultLandingPage':destination})
    assert response.status_code == 403 and response.json()['error']['code'] == 'FORBIDDEN'
    assert await db.users.find_one({'_id':identity[0]['_id']}) == before
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('operation', ['password','preference'])
async def test_profile_api_audit_failure_returns_503_with_persisted_partial_state(client, db, identity, headers, operation):
    await db.command({'collMod':'audit_logs','validator':{'impossible':{'$exists':True}},'validationLevel':'strict'})
    if operation == 'password':
        response = await client.post('/api/auth/change-password', headers=headers, json={'currentPassword':identity[1],'newPassword':'new'})
    else:
        response = await client.put('/api/auth/preferences', headers=headers, json={'defaultLandingPage':'profile'})
    assert response.status_code == 503 and response.json()['error']['code'] == 'AUDIT_WRITE_FAILED'
    assert response.headers['X-Correlation-ID'] and identity[1] not in response.text
    stored = await db.users.find_one({'_id':identity[0]['_id']})
    if operation == 'password': assert await verify_password('new', stored['passwordHash'])
    else: assert stored['defaultLandingPage'] == 'profile'
    assert await db.audit_logs.count_documents({}) == 0

async def test_profile_openapi_methods_are_additive(client):
    paths = (await client.get('/openapi.json')).json()['paths']
    assert 'post' in paths['/api/auth/change-password']
    assert 'put' in paths['/api/auth/preferences']
