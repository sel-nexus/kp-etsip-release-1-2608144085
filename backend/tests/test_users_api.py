"""Exercise every users endpoint with live identities and real Mongo persistence."""
import pytest
from bson import ObjectId
from unittest.mock import patch
from pymongo.errors import AutoReconnect
from api.core.audit import AuditService
from api.core.security import create_access_token, verify_password
from api.core.policy import ROLE_MAXIMUM
from tests.test_users_unit import payload, parent

@pytest.fixture
async def admin(client, db, identity):
    """Promote the fixture account and sign in through the real auth endpoint."""
    user, password = identity
    await db.users.update_one({'_id': user['_id']}, {'$set': {'role': 'Administrator', 'portfolioAccess': []}})
    response = await client.post('/api/auth/login', json={'email': user['email'], 'password': password})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['token']}

async def test_complete_safe_http_journey_and_live_session_changes(client, db, admin):
    """Prove account writes, role audit and next-request token invalidation."""
    first, second = await parent(db), await parent(db, 'Other')
    response = await client.post('/api/users', headers=admin, json=payload('UPPER@EXAMPLE.COM', [str(first)]))
    assert response.status_code == 201
    account = response.json(); identifier = ObjectId(account['id'])
    assert account['email'] == 'upper@example.com'
    assert account['authSource'] == 'local' and account['managerName'] is None
    assert account['vendorIndicator'] is False and account['mustChangePassword'] is False and account['lastLogin'] is None
    assert 'password' not in account and 'passwordHash' not in account
    stored = await db.users.find_one({'_id': identifier})
    assert stored['portfolioAccess'] == [first] and await verify_password('test-secret', stored['passwordHash'])
    login = await client.post('/api/auth/login', json={'email': account['email'], 'password': 'test-secret'})
    assert login.status_code == 200
    token = {'Authorization': 'Bearer ' + login.json()['token']}
    response = await client.put('/api/users/' + account['id'], headers=admin, json={'role': 'Administrator', 'portfolioAccess': [str(second)], 'managerName': 'Manager', 'vendorIndicator': True})
    assert response.status_code == 200 and response.json()['role'] == 'Administrator'
    assert (await client.get('/api/users', headers=token)).status_code == 200
    assert (await client.get('/api/auth/me', headers=token)).json()['portfolioAccess'] == [str(second)]
    response = await client.put('/api/users/' + account['id'], headers=admin, json={'role': 'Read Only'})
    assert response.status_code == 200
    assert (await client.get('/api/users', headers=token)).status_code == 403
    detail = await client.get('/api/users/' + account['id'], headers=admin)
    assert detail.status_code == 200 and detail.json()['lastLogin'] is not None
    assert detail.json()['managerName'] == 'Manager' and detail.json()['vendorIndicator'] is True
    response = await client.delete('/api/users/' + account['id'], headers=admin)
    assert response.status_code == 200 and response.json() == {'deactivated': True, 'id': account['id']}
    assert (await db.users.find_one({'_id': identifier}))['status'] == 'Inactive'
    assert (await client.get('/api/auth/me', headers=token)).status_code == 401
    assert (await client.post('/api/auth/login', json={'email': account['email'], 'password': 'test-secret'})).status_code == 401
    events = await db.audit_logs.find({'entityId': identifier, 'userName': 'Test Engineer'}).to_list(None)
    assert [event['action'] for event in events] == ['create', 'roleChange', 'edit', 'roleChange', 'edit', 'delete']

@pytest.mark.parametrize('role', list(ROLE_MAXIMUM))
async def test_all_roles_administer_boundary(client, db, app, identity, role):
    """Reject every unsupported role on every endpoint before side effects."""
    user, _ = identity
    await db.users.update_one({'_id': user['_id']}, {'$set': {'role': role, 'portfolioAccess': []}})
    headers = {'Authorization': 'Bearer ' + create_access_token(user['_id'], app.state.settings)}
    for method, path, body in [('GET','/api/users',None),('GET','/api/users/'+str(user['_id']),None),('POST','/api/users',payload()),('PUT','/api/users/'+str(user['_id']),{'name':'Changed'}),('DELETE','/api/users/'+str(user['_id']),None)]:
        response = await client.request(method, path, headers=headers, json=body)
        assert response.status_code == (201 if method == 'POST' else 200) if role == 'Administrator' else response.status_code == 403
        if role == 'Administrator' and method == 'DELETE': break
    if role != 'Administrator':
        assert await db.users.count_documents({}) == 1 and await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('field', ['name','email','password','role','portfolioAccess','status'])
async def test_each_missing_create_field_rejects_without_mutation(client, db, admin, field):
    data = payload(); del data[field]
    response = await client.post('/api/users', headers=admin, json=data)
    assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert await db.users.count_documents({}) == 1

@pytest.mark.parametrize('field,value', [('name',''),('name',1),('name','x'*201),('email','bad'),('email',{'$ne':None}),('role','Custom'),('status','Archived'),('portfolioAccess',['bad']),('portfolioAccess',[123456789012345678901234]),('portfolioAccess',None),('portfolioAccess',[str(ObjectId())]),('vendorIndicator','false'),('password',''),('password','é'*37),('passwordHash','secret'),('mustChangePassword',True),('authSource','sso')])
async def test_invalid_body_fields_do_not_mutate(client, db, admin, field, value):
    before = await db.users.find_one({})
    response = await client.post('/api/users', headers=admin, json={**payload(), field:value})
    assert response.status_code == 422
    assert await db.users.find_one({}) == before and await db.users.count_documents({}) == 1
    if field != 'password':
        response = await client.put('/api/users/'+str(before['_id']), headers=admin, json={field:value})
        assert response.status_code == 422
        assert await db.users.find_one({}) == before

@pytest.mark.parametrize('body', [{},{'password':'reset'},{'name':None},{'portfolioAccess':None},{'name':'Edit','expectedUpdatedAt':123},{'name':'Edit','expectedUpdatedAt':'2026-01-01T00:00:00'},{'expectedUpdatedAt':'2026-01-01T00:00:00Z'}])
async def test_invalid_partial_edits(client, db, admin, body):
    before = await db.users.find_one({})
    response = await client.put('/api/users/'+str(before['_id']), headers=admin, json=body)
    assert response.status_code == 422 and await db.users.find_one({}) == before

async def test_duplicate_email_create_edit_and_legacy_case_index(client, db, admin):
    created = await client.post('/api/users', headers=admin, json=payload())
    assert created.status_code == 201
    duplicate = await client.post('/api/users', headers=admin, json=payload('ACCOUNT@EXAMPLE.COM'))
    assert duplicate.status_code == 409
    other = await client.post('/api/users', headers=admin, json=payload('other@example.com'))
    assert other.status_code == 201
    response = await client.put('/api/users/'+other.json()['id'], headers=admin, json={'email':'ACCOUNT@example.com'})
    assert response.status_code == 409
    await db.users.update_one({'_id':ObjectId(created.json()['id'])}, {'$set':{'email':'ACCOUNT@EXAMPLE.COM'}})
    duplicate = await client.post('/api/users', headers=admin, json=payload())
    assert duplicate.status_code == 409

@pytest.mark.parametrize('query', ['unknown=1','page=0','pageSize=101','page=1.2','role=Custom','status=Archived','search=x&search=y','productArea=x'])
async def test_invalid_queries_reject(client, admin, query):
    response = await client.get('/api/users?'+query, headers=admin)
    assert response.status_code == 400 and response.json()['error']['code'] == 'INVALID_FILTER'

async def test_filters_paging_empty_and_stale_delete(client, db, admin):
    for index in range(3):
        assert (await client.post('/api/users',headers=admin,json=payload(f'u{index}@example.com'))).status_code == 201
    response = await client.get('/api/users?search=U&role=Engineer&status=Active&pageSize=2&page=2',headers=admin)
    assert response.status_code == 200
    assert response.json()['total'] == 3 and len(response.json()['items']) == 1
    empty = await client.get('/api/users?search=absent',headers=admin)
    assert empty.status_code == 200 and empty.json()['items'] == []
    account = response.json()['items'][0]
    assert (await client.put('/api/users/'+account['id'],headers=admin,json={'name':'New'})).status_code == 200
    response = await client.delete('/api/users/'+account['id'],headers=admin,params={'expectedUpdatedAt':account['updatedAt']})
    assert response.status_code == 409 and (await db.users.find_one({'_id':ObjectId(account['id'])}))['status'] == 'Active'
    response = await client.put('/api/users/'+account['id'],headers=admin,json={'name':'Loser','expectedUpdatedAt':account['updatedAt']})
    assert response.status_code == 409

@pytest.mark.parametrize('method', ['GET','PUT','DELETE'])
@pytest.mark.parametrize('identifier', ['bad',str(ObjectId())])
async def test_missing_accounts_and_unauthenticated_calls(client, admin, method, identifier):
    response = await client.request(method,'/api/users/'+identifier,headers=admin,json={'name':'Edit'} if method == 'PUT' else None)
    assert response.status_code == 404
    assert (await client.request(method,'/api/users/'+identifier,json={'name':'Edit'} if method == 'PUT' else None)).status_code == 401

@pytest.mark.parametrize('operation', ['create', 'update', 'delete'])
async def test_required_audit_failure_returns_503_with_persisted_partial_write(client, db, admin, operation):
    # Fail only audit acknowledgement; account persistence remains real Mongo.
    if operation != 'create':
        created = await client.post('/api/users', headers=admin, json=payload())
        assert created.status_code == 201
        identifier = created.json()['id']
    audit = AuditService(db)
    async def failure(document):
        raise AutoReconnect('test audit outage')
    from api.domains.users.router import get_service
    from api.domains.users.repository import UserRepository
    from api.domains.users.service import UserService
    with patch.object(audit.collection, 'insert_one', failure):
        client_app = client._transport.app
        client_app.dependency_overrides[get_service] = lambda: UserService(UserRepository(db), audit)
        try:
            if operation == 'create':
                response = await client.post('/api/users', headers=admin, json=payload())
            elif operation == 'update':
                response = await client.put('/api/users/' + identifier, headers=admin, json={'name': 'Persisted edit'})
            else:
                response = await client.delete('/api/users/' + identifier, headers=admin)
        finally:
            client_app.dependency_overrides.clear()
    assert response.status_code == 503 and response.json()['error']['code'] == 'AUDIT_WRITE_FAILED'
    assert response.headers['X-Correlation-ID']
    stored = await db.users.find_one({'email': 'account@example.com'})
    assert stored['status'] == ('Inactive' if operation == 'delete' else 'Active')
    assert stored['name'] == ('Persisted edit' if operation == 'update' else 'Test Account')
    assert await db.audit_logs.count_documents({'action': {'$in': ['edit', 'delete']}}) == 0
    assert await db.audit_logs.count_documents({'action': 'create'}) == (0 if operation == 'create' else 1)


async def test_concurrent_duplicate_email_and_negative_reference_update(client, db, admin):
    """Let Mongo arbitrate duplicate writes and reject missing reference edits without pins."""
    import asyncio
    first, second = await asyncio.gather(
        client.post('/api/users', headers=admin, json=payload('CONCURRENT@example.com')),
        client.post('/api/users', headers=admin, json=payload('concurrent@example.com')),
    )
    assert sorted([first.status_code, second.status_code]) == [201, 409]
    created = first if first.status_code == 201 else second
    identifier = ObjectId(created.json()['id'])
    portfolio = await parent(db)
    before = await db.users.find_one({'_id': identifier})
    parent_before = await db.portfolios.find_one({'_id': portfolio})
    response = await client.put('/api/users/' + str(identifier), headers=admin,
        json={'portfolioAccess': [str(portfolio), str(ObjectId())]})
    assert response.status_code == 422
    assert await db.users.find_one({'_id': identifier}) == before
    assert await db.portfolios.find_one({'_id': portfolio}) == parent_before
    await db.roles.delete_one({'name': 'Engineer'})
    response = await client.put('/api/users/' + str(identifier), headers=admin, json={'role': 'Engineer'})
    assert response.status_code == 422 and await db.users.find_one({'_id': identifier}) == before


@pytest.mark.parametrize('method', ['GET', 'POST', 'PUT', 'DELETE'])
async def test_unknown_query_on_each_account_operation_rejects(client, db, admin, method):
    """Never silently ignore unsupported query filters on account operations."""
    row = await db.users.find_one({})
    path = '/api/users' if method == 'POST' else '/api/users/' + str(row['_id'])
    response = await client.request(method, path + '?unknown=1', headers=admin,
        json=payload() if method == 'POST' else {'name': 'Edit'} if method == 'PUT' else None)
    assert response.status_code == 400
    assert await db.users.find_one({'_id': row['_id']}) == row
    assert await db.users.count_documents({}) == 1
