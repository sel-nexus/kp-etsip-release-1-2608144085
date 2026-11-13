"""Exercise portfolio HTTP policy, validation, conflicts and audit using real Mongo."""
import pytest
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from api.core.security import create_access_token
from api.core.policy import ROLE_MAXIMUM

BODY = {'name': 'Payments', 'ownerName': 'Owner', 'description': 'Payment services', 'productArea': 'Finance', 'status': 'Active'}

@pytest.fixture
async def headers(app, identity, db):
    """Persist an unrestricted admin identity before issuing a subject token."""
    await db.users.update_one({'_id': identity[0]['_id']}, {'$set': {'role': 'Administrator', 'portfolioAccess': []}})
    return {'Authorization': 'Bearer ' + create_access_token(identity[0]['_id'], app.state.settings)}

async def test_api_crud_duplicate_stale_references_and_required_audit(client, db, headers):
    response = await client.post('/api/portfolios', headers=headers, json=BODY)
    assert response.status_code == 201
    item = response.json(); identifier = ObjectId(item['id']); path = '/api/portfolios/' + item['id']
    assert item['applicationCount'] == 0 and item['qualityScore'] is None
    row = await db.portfolios.find_one({'_id': identifier})
    assert row['name'] == BODY['name'] and 'applicationCount' not in row
    duplicate = await client.post('/api/portfolios', headers=headers, json=BODY)
    assert duplicate.status_code == 409 and duplicate.json()['error']['code'] == 'CONFLICT'
    changed = await client.put(path, headers=headers, json={'ownerName': 'Next', 'expectedUpdatedAt': item['updatedAt']})
    assert changed.status_code == 200 and changed.json()['ownerName'] == 'Next'
    before = await db.portfolios.find_one({'_id': identifier})
    stale = await client.put(path, headers=headers, json={'status': 'Archived', 'expectedUpdatedAt': item['updatedAt']})
    assert stale.status_code == 409 and await db.portfolios.find_one({'_id': identifier}) == before
    stale_delete = await client.delete(path, headers=headers, params={'expectedUpdatedAt': item['updatedAt']})
    assert stale_delete.status_code == 409
    await db.applications.insert_one({'name': 'API', 'portfolioId': identifier, 'qualityScore': 82, 'criticality': 'High', 'tier': 2, 'lifecycleStatus': 'Active', 'riskLevel': 'Low', 'secret': 'not exposed'})
    detail = await client.get(path, headers=headers)
    assert detail.status_code == 200 and set(detail.json()) == {'portfolio', 'applications'}
    assert detail.json()['portfolio']['qualityScore'] == 82 and detail.json()['portfolio']['applicationCount'] == 1
    assert 'secret' not in detail.text
    related = await client.get(path + '/applications?pageSize=1', headers=headers)
    assert related.status_code == 200 and related.json()['total'] == 1
    assert set(related.json()['items'][0]) == {'id','name','criticality','tier','lifecycleStatus','riskLevel'}
    denied = await client.delete(path, headers=headers)
    assert denied.status_code == 409 and await db.portfolios.find_one({'_id': identifier}) == before
    assert await db.applications.count_documents({'portfolioId': identifier}) == 1
    await db.applications.delete_many({'portfolioId': identifier})
    deleted = await client.delete(path, headers=headers)
    assert deleted.status_code == 200 and deleted.json() == {'deleted': True, 'id': item['id']}
    assert await db.portfolios.find_one({'_id': identifier}) is None
    assert await db.audit_logs.count_documents({'entityType': 'portfolio', 'entityId': identifier}) == 3

@pytest.mark.parametrize('role', list(ROLE_MAXIMUM))
@pytest.mark.parametrize('assigned', [False, True])
async def test_api_all_role_scope_lists_ids_relations_and_mutations(client, db, identity, headers, role, assigned):
    first = (await client.post('/api/portfolios', headers=headers, json=BODY)).json()
    second = (await client.post('/api/portfolios', headers=headers, json={**BODY, 'name': 'Hidden'})).json()
    await db.users.update_one({'_id': identity[0]['_id']}, {'$set': {'role': role, 'portfolioAccess': [ObjectId(first['id'])] if assigned else []}})
    visible = 1 if assigned else 2 if role in ('Administrator','Executive','Auditor') else 0
    listed = await client.get('/api/portfolios', headers=headers)
    assert listed.status_code == 200 and listed.json()['total'] == visible
    for item, allowed in [(first, visible > 0), (second, visible == 2)]:
        for suffix in ['', '/applications']:
            response = await client.get('/api/portfolios/' + item['id'] + suffix, headers=headers)
            assert response.status_code == (200 if allowed else 404)
    before = await db.portfolios.find_one({'_id': ObjectId(first['id'])})
    if role != 'Administrator':
        for method, path, body in [('post','/api/portfolios', {**BODY, 'name':'Denied'}), ('put','/api/portfolios/' + first['id'], {'status':'Archived'}), ('delete','/api/portfolios/' + first['id'], None)]:
            response = await getattr(client, method)(path, headers=headers, **({'json':body} if body else {}))
            assert response.status_code == 403 and response.json()['error']['code'] == 'FORBIDDEN'
        assert await db.portfolios.find_one({'_id': ObjectId(first['id'])}) == before
    elif assigned:
        for method, kwargs in [('put', {'json':{'status':'Archived'}}), ('delete', {})]:
            assert (await getattr(client, method)('/api/portfolios/' + second['id'], headers=headers, **kwargs)).status_code == 404

@pytest.mark.parametrize('field', list(BODY))
async def test_create_missing_each_required_field_no_writes(client, db, headers, field):
    body = {key:value for key,value in BODY.items() if key != field}
    result = await client.post('/api/portfolios', headers=headers, json=body)
    assert result.status_code == 422 and result.json()['error']['code'] == 'VALIDATION_ERROR'
    assert await db.portfolios.count_documents({}) == 0 and await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('field,value', [(key,value) for key in ['name','ownerName','description','productArea'] for value in ['', '   ', None, 123, {'$ne': None}, 'x'*4001]] + [('status','Inactive'), ('status',None), ('qualityScore',99), ('applicationCount',2), ('_id','f'*24)])
async def test_create_invalid_fields_and_unknown_extras_no_writes(client, db, headers, field, value):
    response = await client.post('/api/portfolios', headers=headers, json={**BODY, field:value})
    assert response.status_code == 422 and await db.portfolios.count_documents({}) == 0

@pytest.mark.parametrize('body', [{}, {'expectedUpdatedAt':'2026-01-01T00:00:00Z'}, {'ownerName':None}, {'name':''}, {'status':'Other'}, {'unknown':1}, {'expectedUpdatedAt':'bad','name':'Next'}, {'expectedUpdatedAt':'2026-01-01','name':'Next'}])
async def test_update_invalid_body_preserves_snapshot(client, db, headers, body):
    item = (await client.post('/api/portfolios', headers=headers, json=BODY)).json()
    before = await db.portfolios.find_one({'_id':ObjectId(item['id'])})
    result = await client.put('/api/portfolios/' + item['id'], headers=headers, json=body)
    assert result.status_code == 422 and await db.portfolios.find_one({'_id':ObjectId(item['id'])}) == before

@pytest.mark.parametrize('query', ['page=0','page=100001','page=1.5','pageSize=0','pageSize=101','status=Other','unknown=x','search=','search='+('x'*201),'productArea=','page=1&page=2','search[$ne]=x'])
async def test_invalid_and_unknown_queries_are_bounded(client, headers, query):
    response = await client.get('/api/portfolios?' + query, headers=headers)
    assert response.status_code == 400 and response.json()['error']['code'] == 'INVALID_FILTER'

async def test_filters_and_pagination_literal_search_and_combined_scope(client, db, identity, headers):
    ids = []
    for name, status, area in [('Pay A','Active','Finance'), ('Pay B','Archived','Finance'), ('Pay C','Active','Other'), ('Pay D','Active','Finance')]:
        result = await client.post('/api/portfolios', headers=headers, json={**BODY,'name':name,'status':status,'productArea':area})
        ids.append(ObjectId(result.json()['id']))
    page = await client.get('/api/portfolios?search=pay&status=Active&productArea=Finance&pageSize=1&page=2',headers=headers)
    assert page.status_code == 200 and page.json()['total'] == 2 and page.json()['items'][0]['name'] == 'Pay D'
    assert (await client.get('/api/portfolios?search=.*',headers=headers)).json()['total'] == 0
    await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'role':'Engineer','portfolioAccess':[ids[0],ids[1]]}})
    page = await client.get('/api/portfolios?search=pay&status=Active&productArea=Finance',headers=headers)
    assert page.json()['total'] == 1 and page.json()['items'][0]['name'] == 'Pay A'

@pytest.mark.parametrize('operation', ['create','update','delete'])
async def test_required_audit_failure_503_preserves_reconciliation_state(client, db, headers, operation):
    item = (await client.post('/api/portfolios',headers=headers,json=BODY)).json()
    await db.command({'collMod':'audit_logs','validator':{'impossible':{'$exists':True}},'validationLevel':'strict'})
    if operation == 'create':
        response = await client.post('/api/portfolios',headers=headers,json={**BODY,'name':'Audit failure'})
        assert await db.portfolios.find_one({'name':'Audit failure'}) is not None
    elif operation == 'update':
        response = await client.put('/api/portfolios/'+item['id'],headers=headers,json={'ownerName':'Updated'})
        assert (await db.portfolios.find_one({'_id':ObjectId(item['id'])}))['ownerName'] == 'Updated'
    else:
        response = await client.delete('/api/portfolios/'+item['id'],headers=headers)
        assert await db.portfolios.find_one({'_id':ObjectId(item['id'])}) is None
    assert response.status_code == 503 and response.json()['error']['code'] == 'AUDIT_WRITE_FAILED'
    assert response.headers['X-Correlation-ID'] and await db.audit_logs.count_documents({}) == 1

@pytest.mark.parametrize('method,suffix,kwargs', [('get','',{}), ('get','/applications',{}), ('put','',{'json':{'name':'Next'}}), ('delete','',{})])
async def test_missing_ids_and_absent_auth(client, headers, method, suffix, kwargs):
    path = '/api/portfolios/'+str(ObjectId())+suffix
    result = await getattr(client,method)(path,headers=headers,**kwargs)
    assert result.status_code == 404 and result.json()['error']['code'] == 'NOT_FOUND'
    assert (await getattr(client,method)(path,**kwargs)).status_code == 401

async def test_related_delete_queries_duplicates_and_user_reference(client, db, identity, headers):
    item=(await client.post('/api/portfolios',headers=headers,json=BODY)).json()
    path='/api/portfolios/'+item['id']
    for suffix in ['/applications?status=Active','/applications?pageSize=101']:
        assert (await client.get(path+suffix,headers=headers)).status_code == 400
    for query in ['unknown=x','expectedUpdatedAt=bad','expectedUpdatedAt=123']:
        assert (await client.delete(path+'?'+query,headers=headers)).status_code == 400
    other=(await client.post('/api/portfolios',headers=headers,json={**BODY,'name':'Other'})).json()
    assert (await client.put(path,headers=headers,json={'name':'Other'})).status_code == 409
    await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'portfolioAccess':[ObjectId(item['id'])]}})
    assert (await client.delete(path,headers=headers)).status_code == 409
    assert await db.portfolios.count_documents({}) == 2

@pytest.mark.parametrize('method,path,kwargs', [('get','/api/portfolios',{}), ('post','/api/portfolios',{'json':BODY}), ('get','/api/portfolios/'+'f'*24,{}), ('get','/api/portfolios/'+'f'*24+'/applications',{}), ('put','/api/portfolios/'+'f'*24,{'json':{'name':'Changed'}}), ('delete','/api/portfolios/'+'f'*24,{})])
@pytest.mark.parametrize('case', ['invalid','expired','inactive','password_gate','permission_removed'])
async def test_every_api_route_auth_policy_boundaries(client, app, db, identity, headers, method, path, kwargs, case):
    """Reject invalid identity or live policy before revealing resources."""
    if case == 'invalid': headers={'Authorization':'Bearer invalid'}
    elif case == 'expired': headers={'Authorization':'Bearer '+create_access_token(identity[0]['_id'],app.state.settings,now=datetime.now(timezone.utc)-timedelta(days=2))}
    elif case == 'inactive': await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'status':'Inactive'}})
    elif case == 'password_gate': await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'mustChangePassword':True}})
    else: await db.roles.update_one({'name':'Administrator'},{'$set':{'permissions':[]}})
    result=await getattr(client,method)(path,headers=headers,**kwargs)
    assert result.status_code == (403 if case in ('password_gate','permission_removed') else 401)
    assert await db.portfolios.count_documents({}) == 0 and await db.audit_logs.count_documents({}) == 0

async def test_related_pagination_counts_full_set_and_unknown_params_reject(client, db, headers):
    """Keep aggregate counts independent from first detail and related page bounds."""
    item=(await client.post('/api/portfolios',headers=headers,json=BODY)).json()
    identifier=ObjectId(item['id']); path='/api/portfolios/'+item['id']
    await db.applications.insert_many([{'name':f'App {i:02}', 'portfolioId':identifier, 'qualityScore': i % 2 + 80, 'criticality':'High', 'tier':2, 'lifecycleStatus':'Active', 'riskLevel':'Low'} for i in range(26)])
    detail=await client.get(path,headers=headers)
    assert detail.status_code == 200 and len(detail.json()['applications']) == 25
    assert detail.json()['portfolio']['applicationCount'] == 26 and detail.json()['portfolio']['qualityScore'] == 81
    related=await client.get(path+'/applications?page=2',headers=headers)
    assert related.status_code == 200 and related.json()['total'] == 26 and related.json()['items'][0]['name'] == 'App 25'
    assert (await client.get('/api/portfolios?page=1.0',headers=headers)).status_code == 400
    assert (await client.put(path,headers=headers,json={'name':'New','expectedUpdatedAt':123})).status_code == 422
