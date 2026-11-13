"""Exercise report scope, fixed DTOs and CSV using disposable real Mongo."""
import csv
from io import StringIO
from datetime import datetime, timezone
import pytest
from bson import ObjectId


APP_COLUMNS = ['id','name','portfolioId','criticality','tier','lifecycleStatus','applicationHealthScore','qualityScore','automationCoverage','unitTestCoverage','openDefects','openCriticalDefects','riskLevel']
PORT_COLUMNS = ['id','name','ownerName','productArea','status','applicationCount','qualityScore']
PATHS = ['/api/reports/applications','/api/reports/portfolios','/api/applications']
ROLES = ['Administrator','Executive','Portfolio Leader','Engineer','Auditor','Read Only']

def application(parent, index=0):
    """Produce complete fake facts, including fields reports must exclude."""
    now = datetime.now(timezone.utc)
    return {'_id':ObjectId(),'name':f'App {index:04}', 'description':'private row detail','portfolioId':parent,'productArea':'Payments','businessOwner':'Owner','technologyOwner':'Tech','etsOwner':'ETS','criticality':'High','tier':2,'lifecycleStatus':'Active','technologyStack':'Python','repositoryUrl':None,'pipelineUrl':None,'applicationHealthScore':82,'qualityScore':79 + index % 2,'automationCoverage':65,'unitTestCoverage':72,'openDefects':4,'openCriticalDefects':1,'riskLevel':'Medium','createdAt':now,'updatedAt':now}

async def inventory(db, count=2):
    """Seed visible, empty and hidden portfolios and multi-batch application rows."""
    ids = [ObjectId() for _ in range(3)]
    now = datetime.now(timezone.utc)
    await db.portfolios.insert_many([{'_id':id,'name':name,'ownerName':'=Test, "Owner"','description':'private portfolio detail','productArea':'Payments','status':'Active','createdAt':now,'updatedAt':now} for id,name in zip(ids,['Payments','Empty','Hidden'])])
    await db.applications.insert_many([application(ids[0],i) for i in range(count)] + [application(ids[2],9999)])
    return ids

async def authorize(client,db,identity,role='Engineer',ids=None):
    """Authenticate real persisted role and assignment changes."""
    user,password = identity
    await db.users.update_one({'_id':user['_id']},{'$set':{'role':role,'portfolioAccess':ids or []}})
    response = await client.post('/api/auth/login',json={'email':user['email'],'password':password})
    assert response.status_code == 200
    return {'Authorization':'Bearer '+response.json()['token']}

def parsed(response):
    """Decode independently of the application serializer."""
    return list(csv.DictReader(StringIO(response.content.decode('utf-8'))))

@pytest.mark.parametrize('role',ROLES)
async def test_roles_assigned_scope_dto_csv_and_live_permissions(client,db,identity,role):
    ids = await inventory(db)
    headers = await authorize(client,db,identity,role,ids[:2])
    for path in PATHS:
        response = await client.get(path,headers=headers)
        assert response.status_code == 200
        assert response.json()['total'] == 2
        if path != '/api/applications':
            assert list(response.json()['items'][0]) == (PORT_COLUMNS if path.endswith('portfolios') else APP_COLUMNS)
        exported = await client.get(path,headers=headers,params={'format':'csv','page':2,'pageSize':1})
        if role == 'Read Only':
            assert exported.status_code == 403
        else:
            assert exported.status_code == 200
            assert 'charset=utf-8' in exported.headers['content-type']
            assert exported.headers['cache-control'] == 'no-store'
            assert exported.headers['content-disposition'].endswith('-report.csv"')
            assert len(parsed(exported)) == 2
            assert 'Hidden' not in exported.text and 'private row detail' not in exported.text
    await db.roles.update_one({'name':role},{'$pull':{'permissions':'export'}})
    for path in PATHS:
        assert (await client.get(path+'?format=csv',headers=headers)).status_code == 403
    await db.roles.update_one({'name':role},{'$pull':{'permissions':'view'}})
    for path in PATHS:
        assert (await client.get(path,headers=headers)).status_code == 403

@pytest.mark.parametrize('role',ROLES)
async def test_empty_assignment_and_current_scope(client,db,identity,role):
    ids = await inventory(db)
    headers = await authorize(client,db,identity,role)
    unrestricted = role in ['Administrator','Executive','Auditor']
    for path in PATHS:
        result = (await client.get(path,headers=headers)).json()
        assert result['total'] == (3 if unrestricted else 0)
    await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'portfolioAccess':[ids[1]]}})
    result = (await client.get('/api/reports/portfolios',headers=headers)).json()
    assert result['items'][0]['applicationCount'] == 0
    assert result['items'][0]['qualityScore'] is None
    assert (await db.portfolios.find_one({'_id':ids[1]})).get('applicationCount') is None

@pytest.mark.parametrize('query',['unknown=x','page=0','pageSize=101','pageSize=0','page=1.5','page=-1','pageSize=true','search=','productArea=%20','format=json','format=csv&format=csv','search=a&search=b','portfolioId[$ne]=x'])
async def test_strict_filters(client,db,identity,query):
    headers = await authorize(client,db,identity,'Administrator')
    for path in PATHS:
        response = await client.get(path+'?'+query,headers=headers)
        assert response.status_code == 400 and response.json()['error']['code'] == 'INVALID_FILTER'

async def test_application_inventory_filter_parity_and_entire_export(client,db,identity):
    ids = await inventory(db,301)
    headers = await authorize(client,db,identity,ids=ids[:2])
    cases = [{'search':'App','name':'00','portfolioId':str(ids[0]),'productArea':'Payments','criticality':'High','tier':'2','lifecycleStatus':'Active','riskLevel':'Medium'},{'portfolioId':str(ids[2])},{'productArea':'Absent'},{'tier':'4'},{'search':'.*'}]
    for filters in cases:
        inventory_page = await client.get('/api/applications',headers=headers,params={**filters,'pageSize':100})
        report = await client.get(PATHS[0],headers=headers,params={**filters,'pageSize':100})
        assert inventory_page.status_code == report.status_code == 200
        assert [r['id'] for r in inventory_page.json()['items']] == [r['id'] for r in report.json()['items']]
        exports = [await client.get(path,headers=headers,params={**filters,'format':'csv','page':99,'pageSize':1}) for path in [PATHS[0],PATHS[2]]]
        assert exports[0].content == exports[1].content
        assert len(parsed(exports[0])) == report.json()['total']
    response = await client.get(PATHS[0]+'?format=csv',headers=headers)
    assert len(parsed(response)) == 301
    events = await db.audit_logs.find({'action':'export','userId':identity[0]['_id']}).to_list(None)
    assert any(event['details'] == 'Exported application report: 301 rows; filter fields: []' for event in events)
    assert all('private' not in row['details'] for row in events)
    for query in ['portfolioId=bad','tier=5','riskLevel=high','criticality=Invalid','lifecycleStatus=Archived']:
        for path in [PATHS[0],PATHS[2]]:
            assert (await client.get(path+'?'+query,headers=headers)).status_code == 400

async def test_portfolio_filters_means_and_empty_csv(client,db,identity):
    ids = await inventory(db)
    headers = await authorize(client,db,identity,ids=ids[:2])
    for filters,total in [({'search':'Pay','status':'Active','productArea':'Payments'},1),({'status':'Archived'},0),({'search':'Hidden'},0),({'productArea':'Missing'},0)]:
        result = await client.get(PATHS[1],headers=headers,params=filters)
        exported = await client.get(PATHS[1],headers=headers,params={**filters,'format':'csv'})
        assert result.status_code == exported.status_code == 200
        assert result.json()['total'] == len(parsed(exported)) == total
        if total:
            assert result.json()['items'][0]['qualityScore'] == 80
            assert parsed(exported)[0]['ownerName'] == '\'=Test, "Owner"'
        else:
            assert exported.text.strip() == ','.join(PORT_COLUMNS)
    assert (await client.get(PATHS[1]+'?status=Retired',headers=headers)).status_code == 400

async def test_auth_gate_inactive_and_audit_failure_before_bytes(client,db,identity):
    await inventory(db)
    for path in PATHS:
        for headers in [{},{'Authorization':'Bearer bad'}]:
            assert (await client.get(path,headers=headers)).status_code == 401
    headers = await authorize(client,db,identity,'Administrator')
    await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'mustChangePassword':True}})
    for path in PATHS:
        assert (await client.get(path,headers=headers)).status_code == 403
    await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'mustChangePassword':False}})
    audits_before = await db.audit_logs.find().sort('_id',1).to_list(None)
    applications_before = await db.applications.find().sort('_id',1).to_list(None)
    portfolios_before = await db.portfolios.find().sort('_id',1).to_list(None)
    await db.command({'collMod':'audit_logs','validator':{'impossible':{'$exists':True}},'validationLevel':'strict','validationAction':'error'})
    try:
        for path in PATHS:
            result = await client.get(path+'?format=csv',headers=headers)
            assert result.status_code == 503 and result.json()['error']['code'] == 'AUDIT_WRITE_FAILED'
            assert 'content-disposition' not in result.headers
            assert await db.audit_logs.find().sort('_id',1).to_list(None) == audits_before
            assert await db.applications.find().sort('_id',1).to_list(None) == applications_before
            assert await db.portfolios.find().sort('_id',1).to_list(None) == portfolios_before
    finally:
        await db.command({'collMod':'audit_logs','validator':{}})
    await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'status':'Inactive'}})
    assert (await client.get(PATHS[0],headers=headers)).status_code == 401
