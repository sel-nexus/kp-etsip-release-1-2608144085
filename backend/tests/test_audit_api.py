"""Exercise audit HTTP filters, six-role security and full CSV parity on Mongo."""
import csv
from datetime import datetime, timezone, timedelta
from io import StringIO
from unittest.mock import patch
import pytest
from bson import ObjectId
from api.core.audit import AuditService
from api.core.security import create_access_token
from api.core.policy import ROLE_MAXIMUM
from api.domains.audit.repository import AuditRepository
from api.domains.audit.service import AuditHistoryService
from api.domains.audit.router import get_service

@pytest.fixture
async def auditor(db, app, identity):
    """Persist the actor and sign a real token for live policy resolution."""
    user, _ = identity
    await db.users.update_one({'_id':user['_id']}, {'$set':{'role':'Auditor'}})
    return {'Authorization':'Bearer '+create_access_token(user['_id'], app.state.settings)}

@pytest.fixture
async def events(db, identity):
    """Persist distinct user, action and boundary dates with secret extra fields."""
    user, _ = identity
    base = datetime(2026,1,1,tzinfo=timezone.utc)
    documents = []
    for day, actor, action, details in [(0,user['_id'],'edit','=formula'), (1,user['_id'],'edit','Quotes, "é"\nnext'), (2,user['_id'],'edit','+formula'), (1,ObjectId(),'edit','Other user'), (1,user['_id'],'login','Other action')]:
        documents.append({'_id':ObjectId(), 'timestamp':base+timedelta(days=day), 'userId':actor, 'userName':'@Test', 'action':action, 'entityType':'application', 'entityId':None, 'details':details, 'passwordHash':'never returned'})
    await db.audit_logs.insert_many(documents)
    return documents

@pytest.mark.parametrize('role', list(ROLE_MAXIMUM))
async def test_six_roles_and_missing_or_invalid_token(client, db, app, identity, role):
    user, _ = identity
    await db.users.update_one({'_id':user['_id']}, {'$set':{'role':role}})
    headers = {'Authorization':'Bearer '+create_access_token(user['_id'], app.state.settings)}
    for suffix in ('','?format=csv'):
        response = await client.get('/api/audit-logs'+suffix, headers=headers)
        assert response.status_code == (200 if role in ('Administrator','Auditor') else 403)
        assert (await client.get('/api/audit-logs'+suffix)).status_code == 401
        assert (await client.get('/api/audit-logs'+suffix, headers={'Authorization':'Bearer invalid'})).status_code == 401
    assert await db.audit_logs.count_documents({'action':'export'}) == (1 if role in ('Administrator','Auditor') else 0)

async def test_and_filters_inclusive_offsets_paging_csv_and_persisted_event(client, db, auditor, identity, events):
    user, _ = identity
    params = {'userId':str(user['_id']), 'action':'edit', 'from':'2026-01-01T01:00:00+01:00', 'to':'2026-01-03T00:00:00Z', 'pageSize':'1', 'page':'2'}
    response = await client.get('/api/audit-logs', headers=auditor, params=params)
    assert response.status_code == 200
    body = response.json()
    assert body['page'] == 2 and body['pageSize'] == 1 and body['total'] == 3
    assert body['items'][0]['id'] == str(events[1]['_id'])
    assert set(body['items'][0]) == {'id','timestamp','userId','userName','action','entityType','entityId','details'}
    full = await client.get('/api/audit-logs', headers=auditor, params={**params,'page':'1','pageSize':'100'})
    assert full.status_code == 200
    exported = await client.get('/api/audit-logs', headers=auditor, params={**params,'format':'csv'})
    assert exported.status_code == 200 and exported.headers['Content-Type'] == 'text/csv; charset=utf-8'
    assert exported.headers['Content-Disposition'] == 'attachment; filename="audit-history.csv"'
    assert exported.headers['Cache-Control'] == 'no-store'
    rows = list(csv.DictReader(StringIO(exported.text)))
    assert len(rows) == 3
    for table, actual in zip(full.json()['items'], rows):
        expected = {key: '' if value is None else str(value) for key, value in table.items() if key != 'id'}
        for key, value in expected.items():
            if value.startswith(('=','+','-','@')): expected[key] = "'"+value
        assert actual == expected
    event = await db.audit_logs.find_one({'action':'export'})
    assert event['userId'] == user['_id'] and event['entityType'] == 'audit' and event['entityId'] is None
    assert '3 rows' in event['details'] and 'passwordHash' not in exported.text and 'never returned' not in event['details']
    assert (await db.audit_logs.find_one({'_id':events[0]['_id']}))['details'] == '=formula'

@pytest.mark.parametrize('params,count', [({'from':'2026-01-03T00:00:00Z'},1), ({'to':'2026-01-01T00:00:00Z'},1), ({'action':'login'},1), ({'from':'2026-01-02T00:00:00Z','to':'2026-01-02T00:00:00Z'},3), ({'page':'100000','pageSize':'100'},0)])
async def test_single_bounds_and_empty_page(client, auditor, events, params, count):
    response = await client.get('/api/audit-logs', headers=auditor, params=params)
    assert response.status_code == 200 and len(response.json()['items']) == count

@pytest.mark.parametrize('query', ['userId=bad','userId=','userId=%7B%22%24ne%22%3Anull%7D','action=unknown','action=','format=json','format=','page=0','page=-1','page=1.5','page=true','page=100001','pageSize=0','pageSize=101','pageSize=1e2','pageSize=','from=bad','from=123','from=2026-01-01','from=2026-01-01T00:00:00','to=2026-01-01T00:00:00','from=2026-02-30T00:00:00Z','from=2026-01-02T00:00:00Z&to=2026-01-01T00:00:00Z','unknown=secret','userId%5B%24ne%5D=1','action=edit&action=login','page=1&page=2','format=csv&format=csv','from=2026-01-01T00:00:00Z&from=2026-01-01T00:00:00Z','to=%3Cscript%3E','userId=..%2F..%2Fetc%2Fpasswd','action='+('x'*1000)])
async def test_invalid_filters_return_safe_400_without_side_effects(client, db, auditor, query):
    response = await client.get('/api/audit-logs?'+query, headers=auditor)
    assert response.status_code == 400 and response.json() == {'error':{'code':'INVALID_FILTER','message':'Invalid audit filters','fields':{}}}
    assert await db.audit_logs.count_documents({}) == 0

async def test_unknown_actor_and_empty_csv_contract(client, db, auditor):
    await AuditService(db).record(None, 'Unknown account', 'login', 'user', None, 'Sign-in failed')
    result = await client.get('/api/audit-logs', headers=auditor)
    assert result.status_code == 200 and result.json()['items'][0]['userId'] is None
    empty = await client.get('/api/audit-logs', headers=auditor, params={'userId':str(ObjectId()),'format':'csv'})
    assert empty.status_code == 200 and empty.text == 'timestamp,userId,userName,action,entityType,entityId,details\r\n'
    assert '0 rows' in (await db.audit_logs.find_one({'action':'export'}))['details']

@pytest.mark.parametrize('permissions,view,export', [([],403,403), (['view'],200,403), (['export'],403,200)])
async def test_live_permission_reduction_checks_export_independently(client, db, auditor, permissions, view, export):
    await db.roles.update_one({'name':'Auditor'}, {'$set':{'permissions':permissions}})
    assert (await client.get('/api/audit-logs', headers=auditor)).status_code == view
    assert (await client.get('/api/audit-logs?format=csv', headers=auditor)).status_code == export
    assert await db.audit_logs.count_documents({'action':'export'}) == (1 if export == 200 else 0)

async def test_export_audit_failure_returns_503_no_csv_or_event(client, db, app, auditor, events):
    """Let Mongo reject the required export event while history remains readable."""
    writer = AuditService(db)
    await db.command({'collMod':'audit_logs', 'validator':{'$jsonSchema':{'required':['sensitive outage payload']}}, 'validationLevel':'strict', 'validationAction':'error'})
    app.dependency_overrides[get_service] = lambda: AuditHistoryService(AuditRepository(db), writer)
    try:
        response = await client.get('/api/audit-logs?format=csv', headers=auditor)
    finally: app.dependency_overrides.pop(get_service)
    assert response.status_code == 503 and response.json()['error']['code'] == 'AUDIT_WRITE_FAILED'
    assert response.headers['X-Correlation-ID'] and 'sensitive' not in response.text
    assert response.headers['Content-Type'].startswith('application/json')
    assert await db.audit_logs.count_documents({}) == 5
    assert await db.audit_logs.count_documents({'action':'export'}) == 0
    assert await db.audit_logs.find({}).sort('_id', 1).to_list(None) == sorted(events, key=lambda row: row['_id'])

async def test_global_audit_despite_assignments_gate_and_no_mutations(client, db, auditor, events):
    response = await client.get('/api/audit-logs', headers=auditor)
    assert response.status_code == 200 and response.json()['total'] == 5
    for method in ('POST','PUT','DELETE'):
        assert (await client.request(method, '/api/audit-logs', headers=auditor)).status_code == 405
    await db.users.update_many({}, {'$set':{'mustChangePassword':True}})
    assert (await client.get('/api/audit-logs', headers=auditor)).status_code == 403
    assert await db.audit_logs.count_documents({}) == 5

@pytest.mark.parametrize('action', ['login','create','edit','delete','roleChange','permissionChange','export'])
async def test_every_supported_action_exact_match_and_bson_actor(client, db, auditor, identity, action):
    """Ensure each action narrows rather than silently ignoring filters."""
    user, _ = identity
    identifier = await AuditService(db).record(user['_id'], user['name'], action, 'user', user['_id'], 'Safe event')
    response = await client.get('/api/audit-logs', headers=auditor, params={'action':action,'userId':str(user['_id']).upper()})
    assert response.status_code == 200 and response.json()['total'] == 1
    assert response.json()['items'][0]['id'] == str(identifier)
    assert response.json()['items'][0]['entityId'] == str(user['_id'])

async def test_failed_csv_generation_is_safe_503_without_success_event(client, db, auditor):
    """Reject generation failure before exposing downloadable bytes."""
    with patch('api.domains.audit.service.csv_line', side_effect=OSError('secret storage location')):
        response = await client.get('/api/audit-logs?format=csv', headers=auditor)
    assert response.status_code == 503 and response.json()['error']['code'] == 'DEPENDENCY_UNAVAILABLE'
    assert 'secret' not in response.text and await db.audit_logs.count_documents({}) == 0
