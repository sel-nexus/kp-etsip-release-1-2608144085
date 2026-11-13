"""Verify real HTTP application policy, schema failures and persisted writes."""
import pytest
from bson import ObjectId
from pymongo.errors import OperationFailure
from api.core.audit import AuditService
from test_applications_unit import payload, parent

async def login(client, db, identity, role='Administrator', parents=()):
    """Reload current stored role and assignments through actual login."""
    user,password = identity
    await db.users.update_one({'_id':user['_id']},{'$set':{'role':role,'portfolioAccess':list(parents)}})
    response = await client.post('/api/auth/login',json={'email':user['email'],'password':password})
    assert response.status_code == 200
    return {'Authorization':'Bearer '+response.json()['token']}

@pytest.mark.parametrize('role', ['Administrator','Executive','Portfolio Leader','Engineer','Auditor','Read Only'])
async def test_six_role_read_write_delete_matrix(client,db,identity,role):
    """All roles view assigned inventory; only approved roles write and admin deletes."""
    portfolio = await parent(db); admin = await login(client,db,identity)
    created = await client.post('/api/applications',headers=admin,json=payload(portfolio)); assert created.status_code == 201
    identifier = created.json()['id']; headers = await login(client,db,identity,role,[portfolio])
    assert (await client.get('/api/applications',headers=headers)).json()['total'] == 1
    detail = await client.get('/api/applications/'+identifier,headers=headers); assert detail.status_code == 200
    assert detail.json()['portfolio'] == {'id':str(portfolio),'name':'Payments','productArea':'Payments','status':'Active'}
    allowed = role in ('Administrator','Portfolio Leader','Engineer')
    response = await client.post('/api/applications',headers=headers,json=payload(portfolio,'New'))
    assert response.status_code == (201 if allowed else 403)
    response = await client.put('/api/applications/'+identifier,headers=headers,json={'qualityScore':83})
    assert response.status_code == (200 if allowed else 403)
    stored = await db.applications.find_one({'_id':ObjectId(identifier)})
    assert stored['qualityScore'] == (83 if allowed else 79)
    response = await client.delete('/api/applications/'+identifier,headers=headers)
    assert response.status_code == (200 if role == 'Administrator' else 403)
    assert (await db.applications.find_one({'_id':ObjectId(identifier)}) is None) == (role == 'Administrator')

async def test_scope_current_destination_empty_and_missing_ids(client,db,identity):
    """Reject hidden current and destination records without leaking their existence."""
    visible,hidden = await parent(db),await parent(db,'Hidden'); headers = await login(client,db,identity)
    created = await client.post('/api/applications',headers=headers,json=payload(hidden)); identifier=created.json()['id']
    headers=await login(client,db,identity,'Engineer',[visible])
    for method,body in [('GET',None),('PUT',{'portfolioId':str(visible)})]:
        response=await client.request(method,'/api/applications/'+identifier,headers=headers,json=body); assert response.status_code == 404
    assert (await client.post('/api/applications',headers=headers,json=payload(hidden,'Hidden destination'))).status_code == 404
    created=await client.post('/api/applications',headers=headers,json=payload(visible,'Visible')); assert created.status_code == 201
    assert (await client.put('/api/applications/'+created.json()['id'],headers=headers,json={'portfolioId':str(hidden)})).status_code == 404
    assert (await db.applications.find_one({'_id':ObjectId(created.json()['id'])}))['portfolioId'] == visible
    headers=await login(client,db,identity,'Engineer',[])
    assert (await client.get('/api/applications',headers=headers)).json()['items'] == []
    assert (await client.post('/api/applications',headers=headers,json=payload(visible,'Unassigned'))).status_code == 404
    headers=await login(client,db,identity)
    for identifier in [str(ObjectId()),'bad']:
        for method,body in [('GET',None),('PUT',{'qualityScore':1}),('DELETE',None)]:
            assert (await client.request(method,'/api/applications/'+identifier,headers=headers,json=body)).status_code == 404

@pytest.mark.parametrize('query', ['portfolioId=bad','page=0','pageSize=101','page=1.2','tier=0','tier=true','criticality=bad','lifecycleStatus=bad','riskLevel=bad','unknown=x','format=csv','page=1&page=2','search='])
async def test_malformed_query_is_400(client,db,identity,query):
    """Keep malformed query errors distinct from invalid body errors."""
    headers=await login(client,db,identity)
    response=await client.get('/api/applications?'+query,headers=headers)
    assert response.status_code == 400 and response.json()['error']['code'] == 'INVALID_FILTER'

async def test_filters_and_paging_are_conjunctive_with_scope(client,db,identity):
    """Exercise every supported filter, literal regex search and matching totals."""
    visible,hidden=await parent(db),await parent(db,'Hidden'); headers=await login(client,db,identity)
    for portfolio,name in [(visible,'Payment [API]'),(visible,'Payment Two'),(hidden,'Payment Hidden')]:
        assert (await client.post('/api/applications',headers=headers,json=payload(portfolio,name))).status_code == 201
    headers=await login(client,db,identity,'Engineer',[visible])
    query={'name':'Payment','search':'[API]','portfolioId':str(visible),'productArea':'Payments','criticality':'High','lifecycleStatus':'Active','riskLevel':'Medium','tier':2,'page':1,'pageSize':1}
    response=await client.get('/api/applications',headers=headers,params=query); assert response.status_code == 200
    assert response.json()['total'] == 1 and response.json()['items'][0]['name'] == 'Payment [API]'
    response=await client.get('/api/applications',headers=headers,params={'page':2,'pageSize':1}); assert response.json()['total']==2 and len(response.json()['items'])==1
    response=await client.get('/api/applications',headers=headers,params={'portfolioId':str(hidden)}); assert response.json()['total']==0

async def test_duplicate_stale_and_validation_preserve_persistence(client,db,identity):
    """Require conflict on duplicates/stale edits and no writes on invalid schemas."""
    portfolio=await parent(db);headers=await login(client,db,identity)
    created=await client.post('/api/applications',headers=headers,json=payload(portfolio)); assert created.status_code==201
    original=created.json();identifier=original['id']
    assert (await client.post('/api/applications',headers=headers,json=payload(portfolio))).status_code==409
    second=await client.post('/api/applications',headers=headers,json=payload(portfolio,'Second'));assert second.status_code==201
    assert (await client.put('/api/applications/'+second.json()['id'],headers=headers,json={'name':original['name']})).status_code==409
    updated=await client.put('/api/applications/'+identifier,headers=headers,json={'qualityScore':100,'expectedUpdatedAt':original['updatedAt']});assert updated.status_code==200
    for method in ['PUT','DELETE']:
        response=await client.request(method,'/api/applications/'+identifier,headers=headers,json={'qualityScore':0,'expectedUpdatedAt':original['updatedAt']} if method=='PUT' else None,params={'expectedUpdatedAt':original['updatedAt']} if method=='DELETE' else None)
        assert response.status_code==409
    for key in payload(portfolio):
        body=payload(portfolio,'Invalid');del body[key]
        assert (await client.post('/api/applications',headers=headers,json=body)).status_code==422
    for body in [{'qualityScore':True},{'portfolioId':'bad'},{'name':' '},{'unknown':1},{'tier':5},{'repositoryUrl':'bad'},{}]:
        assert (await client.put('/api/applications/'+identifier,headers=headers,json=body)).status_code==422
    assert (await db.applications.find_one({'_id':ObjectId(identifier)}))['qualityScore']==100
    assert await db.applications.count_documents({})==2
    assert (await client.delete('/api/applications/'+identifier,headers=headers,params={'expectedUpdatedAt':'bad'})).status_code==400
    assert (await client.get('/api/applications')).status_code==401

@pytest.mark.parametrize('method',['POST','PUT','DELETE'])
async def test_audit_failure_returns_503_after_domain_persists(client,db,identity,monkeypatch,method):
    """Inject only audit failure; never mock the domain database or claim rollback."""
    portfolio=await parent(db);headers=await login(client,db,identity)
    created=await client.post('/api/applications',headers=headers,json=payload(portfolio));identifier=created.json()['id']
    original=AuditService.record
    async def failing(self,*args,**kwargs):
        """Trigger the production audit error mapping through a rejected real write."""
        await db.command({'collMod':'audit_logs','validator':{'forbidden':{'$exists':True}},'validationLevel':'strict'})
        return await original(self,*args,**kwargs)
    monkeypatch.setattr(AuditService,'record',failing)
    response=await client.request(method,'/api/applications' if method=='POST' else '/api/applications/'+identifier,headers=headers,json=payload(portfolio,'After failure') if method=='POST' else {'qualityScore':99} if method=='PUT' else None)
    assert response.status_code==503 and response.json()['error']['code']=='AUDIT_WRITE_FAILED'
    if method=='POST':assert await db.applications.find_one({'name':'After failure'}) is not None
    elif method=='PUT':assert (await db.applications.find_one({'_id':ObjectId(identifier)}))['qualityScore']==99
    else:assert await db.applications.find_one({'_id':ObjectId(identifier)}) is None
