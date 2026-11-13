"""Verify dashboard HTTP contracts against scoped real Mongo documents."""
from datetime import datetime, timezone
import pytest
from bson import ObjectId

ROLES=['Administrator','Executive','Portfolio Leader','Engineer','Auditor','Read Only']

async def inventory(db):
    """Create two represented portfolios, one empty visible and one hidden."""
    ids=[ObjectId() for _ in range(4)]
    now=datetime.now(timezone.utc)
    await db.portfolios.insert_many([{'_id':id,'name':name,'ownerName':'Test','description':'Test','productArea':'Portfolio area differs','status':'Archived' if index==2 else 'Active','createdAt':now,'updatedAt':now} for index,(id,name) in enumerate(zip(ids,['Payments','Claims','Empty','Hidden']))])
    facts=[(ids[0],79,80,50,3,'High','Payments'),(ids[0],80,81,51,4,'Low','Payments'),(ids[1],0,100,100,2,'Medium','Claims'),(ids[3],100,0,0,99,'High','Payments')]
    await db.applications.insert_many([{'name':f'App {index}','portfolioId':p,'qualityScore':q,'applicationHealthScore':h,'automationCoverage':a,'openCriticalDefects':d,'riskLevel':r,'productArea':area} for index,(p,q,h,a,d,r,area) in enumerate(facts)])
    return ids

async def authorize(client,db,identity,role,ids):
    """Log in with current persisted assignments and role permissions."""
    user,password=identity
    await db.users.update_one({'_id':user['_id']},{'$set':{'role':role,'portfolioAccess':ids}})
    response=await client.post('/api/auth/login',json={'email':user['email'],'password':password})
    assert response.status_code==200
    return {'Authorization':'Bearer '+response.json()['token']}

@pytest.mark.parametrize('role',ROLES)
async def test_all_roles_assigned_scope_exact_metrics_and_labels(client,db,identity,role):
    """All six view roles get identical scoped numbers and no hidden names."""
    ids=await inventory(db)
    headers=await authorize(client,db,identity,role,ids[:3])
    response=await client.get('/api/dashboard/executive',headers=headers)
    assert response.status_code==200
    assert response.json()=={'metrics':{'enterpriseQualityScore':53,'averageApplicationHealthScore':87,'automationMaturityScore':67,'openCriticalDefects':9,'applicationsAtRisk':1,'totalApplications':3,'totalPortfolios':3},'portfolioComparisons':[{'portfolioId':str(ids[1]),'name':'Claims','qualityScore':0,'applicationsAtRisk':0},{'portfolioId':str(ids[0]),'name':'Payments','qualityScore':80,'applicationsAtRisk':1}]}
    assert response.headers['cache-control']=='no-store'

@pytest.mark.parametrize('role',ROLES)
async def test_empty_assignment_semantics_and_live_view_reduction(client,db,identity,role):
    """Only three roles have unrestricted empty assignments; view is independently required."""
    await inventory(db)
    headers=await authorize(client,db,identity,role,[])
    response=await client.get('/api/dashboard/executive',headers=headers)
    assert response.status_code==200
    unrestricted=role in ['Administrator','Executive','Auditor']
    assert response.json()['metrics']['totalApplications']==(4 if unrestricted else 0)
    assert response.json()['metrics']['totalPortfolios']==(4 if unrestricted else 0)
    if not unrestricted:
        assert response.json()['metrics']['enterpriseQualityScore'] is None
        assert response.json()['portfolioComparisons']==[]
    await db.roles.update_one({'name':role},{'$pull':{'permissions':'view'}})
    denied=await client.get('/api/dashboard/executive',headers=headers)
    assert denied.status_code==403 and denied.json()['error']['code']=='FORBIDDEN'

@pytest.mark.parametrize('query', ['portfolioId=bad','portfolioId=','riskLevel=Critical','riskLevel=high','riskLevel=','productArea=','productArea=%20','productArea='+('x'*201),'unknown=x','page=1','format=csv','riskLevel=High&riskLevel=Low','portfolioId=65b100000000000000000001&portfolioId=65b100000000000000000001','productArea=A&productArea=B','portfolioId[$ne]=x'])
async def test_invalid_unknown_repeated_filters_are_400(client,db,identity,query):
    """Reject unsupported query syntax rather than querying or silently ignoring it."""
    headers=await authorize(client,db,identity,'Administrator',[])
    response=await client.get('/api/dashboard/executive?'+query,headers=headers)
    assert response.status_code==400 and response.json()['error']['code']=='INVALID_FILTER'

async def test_filter_intersections_never_narrow_portfolio_document_count(client,db,identity):
    """All three filters intersect app facts; total portfolios ignores every filter."""
    ids=await inventory(db)
    headers=await authorize(client,db,identity,'Engineer',ids[:3])
    cases=[({'portfolioId':str(ids[0])},2,80,7,1),({'productArea':'Payments'},2,80,7,1),({'riskLevel':'High'},1,79,3,1),({'portfolioId':str(ids[0]),'productArea':'Payments','riskLevel':'High'},1,79,3,1),({'portfolioId':str(ids[0]),'productArea':'Claims'},0,None,0,0),({'productArea':'Payments','riskLevel':'Medium'},0,None,0,0),({'portfolioId':str(ids[3])},0,None,0,0),({'portfolioId':str(ObjectId())},0,None,0,0),({'portfolioId':str(ids[2])},0,None,0,0)]
    for filters,count,quality,defects,risk in cases:
        response=await client.get('/api/dashboard/executive',headers=headers,params=filters)
        assert response.status_code==200
        metrics=response.json()['metrics']
        assert metrics['totalPortfolios']==3 and metrics['totalApplications']==count
        assert metrics['enterpriseQualityScore']==quality and metrics['openCriticalDefects']==defects and metrics['applicationsAtRisk']==risk
        assert len(response.json()['portfolioComparisons'])==(1 if count else 0)
    await db.portfolios.update_one({'_id':ids[0]},{'$set':{'name':'Renamed by backend'}})
    response=await client.get('/api/dashboard/executive',headers=headers,params={'portfolioId':str(ids[0])})
    assert response.json()['portfolioComparisons'][0]['name']=='Renamed by backend'
    await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'portfolioAccess':[ids[2]]}})
    response=await client.get('/api/dashboard/executive',headers=headers)
    assert response.json()['metrics']['totalPortfolios']==1
    assert response.json()['metrics']['totalApplications']==0

async def test_authentication_gate_and_no_data(client,db,identity):
    """Reject missing/invalid/inactive identity and the first-password gate."""
    for headers in [{},{'Authorization':'Bearer invalid'}]:
        response=await client.get('/api/dashboard/executive',headers=headers)
        assert response.status_code==401
    headers=await authorize(client,db,identity,'Administrator',[])
    response=await client.get('/api/dashboard/executive',headers=headers)
    assert response.status_code==200 and response.json()['metrics']['totalPortfolios']==0
    await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'mustChangePassword':True}})
    response=await client.get('/api/dashboard/executive',headers=headers)
    assert response.status_code==403 and response.json()['error']['code']=='PASSWORD_CHANGE_REQUIRED'
    await db.users.update_one({'_id':identity[0]['_id']},{'$set':{'status':'Inactive'}})
    assert (await client.get('/api/dashboard/executive',headers=headers)).status_code==401

async def test_large_dataset_is_not_limited_to_inventory_page(client,db,identity):
    """Aggregate all 301 visible apps without including 300 hidden rows."""
    ids=await inventory(db)
    await db.applications.delete_many({})
    await db.applications.insert_many([{'name':f'Bulk {i}','portfolioId':ids[0] if i<301 else ids[3],'qualityScore':i%2,'applicationHealthScore':100,'automationCoverage':0,'openCriticalDefects':2,'riskLevel':'High' if i%2 else 'Low','productArea':'Bulk'} for i in range(601)])
    headers=await authorize(client,db,identity,'Read Only',ids[:3])
    response=await client.get('/api/dashboard/executive',headers=headers,params={'productArea':'Bulk'})
    assert response.status_code==200
    assert response.json()['metrics']=={'enterpriseQualityScore':0,'averageApplicationHealthScore':100,'automationMaturityScore':0,'openCriticalDefects':602,'applicationsAtRisk':150,'totalApplications':301,'totalPortfolios':3}
    assert response.json()['portfolioComparisons']==[{'portfolioId':str(ids[0]),'name':'Payments','qualityScore':0,'applicationsAtRisk':150}]
