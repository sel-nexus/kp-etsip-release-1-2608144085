"""Verify exact auth contracts and live authorization through real Mongo HTTP tests."""
import pytest
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from jose import jwt
from api.core.security import create_access_token
from api.core.dependencies import permission_dependency
from fastapi import Depends

async def test_login_me_logout_persist_and_privacy(client, db, identity):
    user, password = identity
    response = await client.post('/api/auth/login', json={'email': ' ENGINEER@EXAMPLE.COM ', 'password': password})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {'token', 'user'}
    assert body['user']['id'] == str(user['_id'])
    headers = {'Authorization': 'Bearer ' + body['token']}
    me = await client.get('/api/auth/me', headers=headers)
    assert me.status_code == 200
    assert me.json() == body['user']
    assert set(me.json()) == {'id','name','email','role','portfolioAccess','status','defaultLandingPage','mustChangePassword'}
    assert password not in me.text and 'passwordHash' not in response.text
    stored = await db.users.find_one({'_id': user['_id']})
    assert stored['lastLogin'] is not None and stored['passwordHash'] == user['passwordHash']
    event = await db.audit_logs.find_one({'userId': user['_id']})
    assert event['details'] == 'Sign-in succeeded' and event['action'] == 'login'
    assert event['timestamp'].tzinfo is not None
    logout = await client.post('/api/auth/logout', headers=headers)
    assert logout.status_code == 200 and logout.json() == {'message': 'Signed out'}
    assert (await client.get('/api/auth/me', headers=headers)).status_code == 200  # no revocation contract

@pytest.mark.parametrize('change', ['wrong', 'missing', 'inactive', 'role_missing'])
async def test_invalid_login_generic_audited_no_timestamp(client, db, identity, change):
    user, password = identity
    email = user['email']
    if change == 'wrong': password = 'not-the-credential'
    if change == 'missing': email = 'missing@example.com'
    if change == 'inactive': await db.users.update_one({'_id': user['_id']}, {'$set': {'status': 'Inactive'}})
    if change == 'role_missing': await db.roles.delete_one({'name': user['role']})
    response = await client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 401
    assert response.json() == {'error': {'code':'UNAUTHENTICATED','message':'Unable to authenticate','fields':{}}}
    assert (await db.users.find_one({'_id':user['_id']}))['lastLogin'] is None
    event = await db.audit_logs.find_one({})
    assert event['details'] == 'Sign-in failed' and password not in str(event)
    if change == 'missing':
        assert event['userId'] is None and event['entityId'] is None
        assert event['userName'] == 'Unknown account' and email not in str(event)

@pytest.mark.parametrize('payload', [{}, {'email':'x@example.com'}, {'password':'sensitive-value'}, {'email':{'$ne':None},'password':'sensitive-value'}, {'email':'bad','password':'sensitive-value'}, {'email':'x@example.com','password':123}, {'email':'x@example.com','password':''}, {'email':'x@example.com','password':'sensitive-value','sensitive-value':'secret'}])
async def test_validation_never_echoes_secrets_or_writes(client, db, payload):
    response = await client.post('/api/auth/login', json=payload)
    assert response.status_code == 422
    assert response.json() == {'error': {'code':'VALIDATION_ERROR','message':'Invalid request','fields':{}}}
    assert 'sensitive-value' not in response.text
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('path,method', [('/api/auth/me','get'),('/api/auth/logout','post')])
@pytest.mark.parametrize('token', [None, 'bad.token.value', ''])
async def test_protected_routes_require_valid_bearer(client, path, method, token):
    response = await getattr(client,method)(path, headers={} if token is None else {'Authorization':'Bearer '+token})
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'UNAUTHENTICATED'

@pytest.mark.parametrize('kind', ['expired','wrong_key','wrong_issuer','missing_exp','bad_subject','missing_user'])
async def test_token_claim_boundaries(client, app, identity, kind):
    user,_ = identity
    settings = app.state.settings
    now = datetime.now(timezone.utc)
    claims = {'sub':str(user['_id']), 'iat':now, 'exp':now+timedelta(hours=8), 'iss':settings.JWT_ISSUER}
    key = settings.JWT_SECRET.get_secret_value()
    if kind == 'expired': claims['exp'] = now-timedelta(minutes=1)
    if kind == 'wrong_key': key = 'different-generated-signing-key-for-testing'
    if kind == 'wrong_issuer': claims['iss'] = 'other'
    if kind == 'missing_exp': del claims['exp']
    if kind == 'bad_subject': claims['sub'] = 'not-an-id'
    if kind == 'missing_user': claims['sub'] = str(ObjectId())
    response = await client.get('/api/auth/me', headers={'Authorization':'Bearer '+jwt.encode(claims,key,algorithm='HS256')})
    assert response.status_code == 401

async def test_role_status_assignments_and_gate_reload_per_call(client, app, db, identity):
    user,_ = identity
    token = create_access_token(user['_id'], app.state.settings)
    headers = {'Authorization':'Bearer '+token}
    # Test-only protected probe exercises shared dependencies, not another feature router.
    @app.get('/api/test-policy', dependencies=[Depends(permission_dependency('edit','application'))])
    async def probe():
        return {'allowed':True}
    assert (await client.get('/api/test-policy',headers=headers)).status_code == 200
    await db.roles.update_one({'name':'Engineer'},{'$set':{'permissions':['view']}})
    assert (await client.get('/api/test-policy',headers=headers)).status_code == 403
    await db.users.update_one({'_id':user['_id']},{'$set':{'role':'Executive','portfolioAccess':[],'mustChangePassword':True}})
    me = await client.get('/api/auth/me',headers=headers)
    assert me.status_code == 200 and me.json()['role'] == 'Executive' and me.json()['portfolioAccess'] == []
    assert (await client.get('/api/test-policy',headers=headers)).json()['error']['code'] == 'PASSWORD_CHANGE_REQUIRED'
    assert (await client.post('/api/auth/logout',headers=headers)).status_code == 200
    await db.users.update_one({'_id':user['_id']},{'$set':{'status':'Inactive'}})
    assert (await client.get('/api/auth/me',headers=headers)).status_code == 401

async def test_login_audit_failure_returns_reconciliation_error(client, db, identity):
    user, password = identity
    await db.command({'collMod': 'audit_logs', 'validator': {'impossible': {'$exists': True}}, 'validationLevel': 'strict'})
    response = await client.post('/api/auth/login', json={'email': user['email'], 'password': password})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'AUDIT_WRITE_FAILED'
    assert response.headers['X-Correlation-ID']
    assert password not in response.text and 'token' not in response.json()
    assert (await db.users.find_one({'_id': user['_id']}))['lastLogin'] is not None
    assert await db.audit_logs.count_documents({}) == 0

async def test_prescribed_local_account_email_can_sign_in(client, db, identity):
    user, password = identity
    await db.users.update_one({'_id': user['_id']}, {'$set': {'email': 'admin@ketsip.local'}})
    response = await client.post('/api/auth/login', json={'email': 'ADMIN@KETSIP.LOCAL', 'password': password})
    assert response.status_code == 200
    assert response.json()['user']['email'] == 'admin@ketsip.local'

async def test_health_and_openapi_exact_routes(client):
    health = await client.get('/api/health')
    assert health.status_code == 200 and health.json() == {'status':'ok'}
    paths = (await client.get('/openapi.json')).json()['paths']
    assert {'/api/auth/login','/api/auth/logout','/api/auth/me','/api/health'} <= set(paths)
