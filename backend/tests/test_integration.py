"""Verify identity, administration, inventory, insight and audit crossings."""
import csv
import io
import secrets
from typing import Any
from bson import ObjectId
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase
from api.core.config import Settings
from api.seed.runner import seed_database


async def establish(client, db):
    """Seed isolated records and pass the initial administrator credential gate."""
    password = secrets.token_urlsafe(24)
    await seed_database(db, Settings(SEED_ADMIN_PASSWORD=password, SEED_DEMO_PASSWORD=password))
    login = await client.post('/api/auth/login', json={'email': 'admin@ketsip.local', 'password': password})
    assert login.status_code == 200
    headers = {'Authorization': 'Bearer ' + login.json()['token']}
    changed = await client.post('/api/auth/change-password', headers=headers, json={'currentPassword': password, 'newPassword': secrets.token_urlsafe(24)})
    assert changed.status_code == 200 and changed.json()['mustChangePassword'] is False
    return headers


async def assert_inventory_reads(
    client: AsyncClient, headers: dict[str, str], portfolio: str,
    facts: dict[str, Any] | None, total_portfolios: int, *, exports: bool = True,
) -> None:
    """Requery each consumer after a mutation, including both report formats."""
    detail = await client.get('/api/portfolios/' + portfolio, headers=headers)
    assert detail.status_code == 200
    parent = detail.json()['portfolio']
    count = 0 if facts is None else 1
    quality = None if facts is None else facts['qualityScore']
    assert parent['id'] == portfolio
    assert parent['applicationCount'] == count and parent['qualityScore'] == quality
    related = detail.json()['applications']
    if facts is None:
        assert related == []
    else:
        assert len(related) == 1
        assert related[0]['id'] == facts['id'] and related[0]['riskLevel'] == facts['riskLevel']
        application = await client.get('/api/applications/' + facts['id'], headers=headers)
        assert application.status_code == 200
        assert all(application.json()[key] == value for key, value in facts.items())
        assert application.json()['portfolio']['id'] == portfolio

    dashboard = await client.get('/api/dashboard/executive', headers=headers, params={'portfolioId': portfolio})
    assert dashboard.status_code == 200
    at_risk = 0 if facts is None else int(facts['riskLevel'] == 'High')
    assert dashboard.json()['metrics'] == {
        'enterpriseQualityScore': quality,
        'averageApplicationHealthScore': None if facts is None else facts['applicationHealthScore'],
        'automationMaturityScore': None if facts is None else facts['automationCoverage'],
        'openCriticalDefects': 0 if facts is None else facts['openCriticalDefects'],
        'applicationsAtRisk': at_risk, 'totalApplications': count,
        'totalPortfolios': total_portfolios,
    }
    assert dashboard.json()['portfolioComparisons'] == ([] if facts is None else [{
        'portfolioId': portfolio, 'name': parent['name'],
        'qualityScore': quality, 'applicationsAtRisk': at_risk,
    }])

    for resource, filters in [
        ('applications', {'portfolioId': portfolio}),
        ('portfolios', {'productArea': parent['productArea']}),
    ]:
        report = await client.get('/api/reports/' + resource, headers=headers, params=filters)
        assert report.status_code == 200
        items = report.json()['items']
        assert report.json()['total'] == (count if resource == 'applications' else 1)
        if resource == 'applications':
            expected = [] if facts is None else [{key: facts[key] for key in (
                'id', 'name', 'portfolioId', 'criticality', 'tier', 'lifecycleStatus',
                'applicationHealthScore', 'qualityScore', 'automationCoverage',
                'unitTestCoverage', 'openDefects', 'openCriticalDefects', 'riskLevel',
            )}]
        else:
            expected = [{key: parent[key] for key in (
                'id', 'name', 'ownerName', 'productArea', 'status', 'applicationCount', 'qualityScore',
            )}]
        assert items == expected
        if exports:
            export = await client.get('/api/reports/' + resource, headers=headers, params={**filters, 'format': 'csv'})
            assert export.status_code == 200
            rows = list(csv.DictReader(io.StringIO(export.text)))
            assert rows == [{key: '' if value is None else str(value) for key, value in row.items()} for row in expected]


async def test_inventory_to_dashboard_reports_audit_and_live_access(client, db):
    """Follow persisted records across six routers and live permission changes."""
    admin = await establish(client, db)
    created = await client.post('/api/portfolios', headers=admin, json={'name': 'Integration', 'ownerName': 'Fake owner', 'description': 'Isolated crossing', 'productArea': 'Integration', 'status': 'Active'})
    assert created.status_code == 201
    portfolio = created.json()['id']
    password = secrets.token_urlsafe(24)
    account = await client.post('/api/users', headers=admin, json={'name': 'Integration engineer', 'email': 'crossing@example.com', 'password': password, 'role': 'Engineer', 'portfolioAccess': [portfolio], 'status': 'Active'})
    assert account.status_code == 201
    login = await client.post('/api/auth/login', json={'email': 'crossing@example.com', 'password': password})
    assert login.status_code == 200
    engineer = {'Authorization': 'Bearer ' + login.json()['token']}
    payload = {'name': 'Crossing application', 'description': 'Test facts', 'portfolioId': portfolio, 'productArea': 'Integration', 'businessOwner': 'Fake business', 'technologyOwner': 'Fake technology', 'etsOwner': 'Fake quality', 'criticality': 'High', 'tier': 2, 'lifecycleStatus': 'Active', 'technologyStack': 'Python', 'repositoryUrl': None, 'pipelineUrl': None, 'applicationHealthScore': 82, 'qualityScore': 79, 'automationCoverage': 65, 'unitTestCoverage': 72, 'openDefects': 4, 'openCriticalDefects': 1, 'riskLevel': 'High'}
    application = await client.post('/api/applications', headers=engineer, json=payload)
    assert application.status_code == 201
    identifier = application.json()['id']
    metrics = await client.get('/api/dashboard/executive', headers=engineer)
    assert metrics.status_code == 200
    assert metrics.json()['metrics'] == {'enterpriseQualityScore': 79, 'averageApplicationHealthScore': 82, 'automationMaturityScore': 65, 'openCriticalDefects': 1, 'applicationsAtRisk': 1, 'totalApplications': 1, 'totalPortfolios': 1}
    detail = await client.get('/api/portfolios/' + portfolio, headers=engineer)
    assert detail.status_code == 200 and detail.json()['portfolio']['applicationCount'] == 1
    report = await client.get('/api/reports/applications', headers=engineer)
    assert report.status_code == 200 and report.json()['items'][0]['id'] == identifier
    export = await client.get('/api/reports/applications?format=csv', headers=engineer)
    assert export.status_code == 200
    rows = list(csv.DictReader(io.StringIO(export.text)))
    assert len(rows) == 1 and rows[0]['name'] == payload['name']
    await assert_inventory_reads(client, engineer, portfolio, {**payload, 'id': identifier}, 1)
    changes = {'qualityScore': 93, 'riskLevel': 'Low', 'openCriticalDefects': 0}
    updated = await client.put('/api/applications/' + identifier, headers=engineer, json=changes)
    assert updated.status_code == 200
    assert all(updated.json()[key] == value for key, value in changes.items())
    persisted = await db.applications.find_one({'_id': ObjectId(identifier)})
    assert persisted is not None and persisted['portfolioId'] == ObjectId(portfolio)
    assert all(persisted[key] == value for key, value in changes.items())
    await assert_inventory_reads(client, engineer, portfolio, {**payload, **changes, 'id': identifier}, 1)
    edits = await client.get('/api/audit-logs', headers=admin, params={'userId': account.json()['id'], 'action': 'edit', 'pageSize': 100})
    assert edits.status_code == 200
    assert any(row['entityType'] == 'application' and row['entityId'] == identifier for row in edits.json()['items'])
    history = await client.get('/api/audit-logs', headers=admin, params={'userId': account.json()['id'], 'pageSize': 100})
    assert history.status_code == 200
    assert {'login', 'create', 'export'} <= {row['action'] for row in history.json()['items']}
    denied = await client.delete('/api/portfolios/' + portfolio, headers=admin)
    assert denied.status_code == 409
    assert await db.applications.find_one({'_id': ObjectId(identifier)}) is not None
    reassigned = await client.put('/api/users/' + account.json()['id'], headers=admin, json={'portfolioAccess': []})
    assert reassigned.status_code == 200
    assert (await client.get('/api/applications', headers=engineer)).json()['total'] == 0
    assert (await client.get('/api/applications/' + identifier, headers=engineer)).status_code == 404
    assert (await client.get('/api/reports/applications?format=csv', headers=engineer)).text.count('\n') == 1
    deactivated = await client.delete('/api/users/' + account.json()['id'], headers=admin)
    assert deactivated.status_code == 200
    assert (await client.get('/api/auth/me', headers=engineer)).status_code == 401
    stored = await db.users.find_one({'_id': ObjectId(account.json()['id'])})
    assert stored['status'] == 'Inactive' and stored['portfolioAccess'] == []
    removed = await client.delete('/api/applications/' + identifier, headers=admin)
    assert removed.status_code == 200 and removed.json() == {'deleted': True, 'id': identifier}
    assert await db.applications.find_one({'_id': ObjectId(identifier)}) is None
    assert (await client.get('/api/applications/' + identifier, headers=admin)).status_code == 404
    await assert_inventory_reads(client, admin, portfolio, None, await db.portfolios.count_documents({}))
    # User assignments were cleared above; deletion must not leave dangling references.
    assert await db.users.count_documents({'portfolioAccess': ObjectId(portfolio)}) == 0
    safe_delete = await client.delete('/api/portfolios/' + portfolio, headers=admin)
    assert safe_delete.status_code == 200 and safe_delete.json() == {'deleted': True, 'id': portfolio}
    assert await db.portfolios.find_one({'_id': ObjectId(portfolio)}) is None
    assert await db.applications.count_documents({'portfolioId': ObjectId(portfolio)}) == 0
    assert (await client.get('/api/portfolios/' + portfolio, headers=admin)).status_code == 404
    for format_params in [{}, {'format': 'csv'}]:
        remaining = await client.get('/api/reports/portfolios', headers=admin, params={'productArea': 'Integration', **format_params})
        assert remaining.status_code == 200
        if format_params:
            assert list(csv.DictReader(io.StringIO(remaining.text))) == []
        else:
            assert remaining.json()['total'] == 0 and remaining.json()['items'] == []
    deletions = await client.get('/api/audit-logs', headers=admin, params={'action': 'delete', 'pageSize': 100})
    assert deletions.status_code == 200
    assert {('application', identifier), ('portfolio', portfolio)} <= {
        (row['entityType'], row['entityId']) for row in deletions.json()['items']
    }


async def test_role_reduction_and_invalid_upstream_do_not_leak_or_orphan(client, db, app):
    """Propagate invalid references and live role changes through downstream reads."""
    admin = await establish(client, db)
    roles = await client.get('/api/roles', headers=admin)
    assert roles.status_code == 200
    readonly = next(role for role in roles.json()['items'] if role['name'] == 'Read Only')
    user = await db.users.find_one({'role': 'Read Only'})
    from api.core.security import create_access_token
    token = create_access_token(user['_id'], app.state.settings)
    headers = {'Authorization': 'Bearer ' + token}
    assert (await client.get('/api/reports/applications?format=csv', headers=headers)).status_code == 403
    reduced = await client.put('/api/roles/' + readonly['id'], headers=admin, json={'permissions': []})
    assert reduced.status_code == 200
    for endpoint in ['/api/applications', '/api/portfolios', '/api/dashboard/executive', '/api/reports/applications']:
        assert (await client.get(endpoint, headers=headers)).status_code == 403
    before = await db.users.count_documents({})
    invalid = await client.post('/api/users', headers=admin, json={'name': 'Invalid reference', 'email': 'invalid-reference@example.com', 'password': secrets.token_urlsafe(24), 'role': 'Engineer', 'portfolioAccess': [str(ObjectId())], 'status': 'Active'})
    assert invalid.status_code == 422
    assert await db.users.count_documents({}) == before
    for application in await db.applications.find({}).to_list(None):
        assert await db.portfolios.find_one({'_id': application['portfolioId']}) is not None


async def test_rejected_audit_write_exposes_persisted_update_without_successful_export(
    client: AsyncClient, db: AsyncDatabase,
) -> None:
    """Use a real Mongo validator to prove partial state and fail-closed exports."""
    admin = await establish(client, db)
    created = await client.post('/api/portfolios', headers=admin, json={
        'name': 'Audit failure crossing', 'ownerName': 'Fake owner',
        'description': 'Isolated dependency failure', 'productArea': 'Audit failure crossing', 'status': 'Active',
    })
    assert created.status_code == 201
    portfolio = created.json()['id']
    payload = {
        'name': 'Persisted despite audit failure', 'description': 'Test facts', 'portfolioId': portfolio,
        'productArea': 'Audit failure crossing', 'businessOwner': 'Fake business',
        'technologyOwner': 'Fake technology', 'etsOwner': 'Fake quality', 'criticality': 'High',
        'tier': 2, 'lifecycleStatus': 'Active', 'technologyStack': 'Python',
        'repositoryUrl': None, 'pipelineUrl': None, 'applicationHealthScore': 82,
        'qualityScore': 79, 'automationCoverage': 65, 'unitTestCoverage': 72,
        'openDefects': 4, 'openCriticalDefects': 1, 'riskLevel': 'High',
    }
    application = await client.post('/api/applications', headers=admin, json=payload)
    assert application.status_code == 201
    identifier = application.json()['id']
    total_portfolios = await db.portfolios.count_documents({})
    await assert_inventory_reads(client, admin, portfolio, {**payload, 'id': identifier}, total_portfolios)
    audit_before = await db.audit_logs.count_documents({})
    options = await db.audit_logs.options()
    changes = {'qualityScore': 96, 'riskLevel': 'Low', 'openCriticalDefects': 0}
    try:
        await db.command({
            'collMod': 'audit_logs', 'validator': {'integrationRejectAudit': {'$exists': True}},
            'validationLevel': 'strict', 'validationAction': 'error',
        })
        failed = await client.put('/api/applications/' + identifier, headers=admin, json=changes)
        assert failed.status_code == 503
        assert failed.json() == {'error': {'code': 'AUDIT_WRITE_FAILED', 'message': 'Required audit could not be recorded', 'fields': {}}}
        assert failed.headers.get('X-Correlation-ID')
        # Standalone Mongo does not roll back the inventory write when required audit fails.
        persisted = await db.applications.find_one({'_id': ObjectId(identifier)})
        assert persisted is not None and persisted['portfolioId'] == ObjectId(portfolio)
        assert all(persisted[key] == value for key, value in changes.items())
        parent = await db.portfolios.find_one({'_id': ObjectId(portfolio)})
        assert parent is not None and parent.get('_applicationReservations', []) == []
        assert await db.audit_logs.count_documents({}) == audit_before
        assert await db.audit_logs.count_documents({'entityId': ObjectId(identifier), 'action': 'edit'}) == 0
        await assert_inventory_reads(client, admin, portfolio, {**payload, **changes, 'id': identifier}, total_portfolios, exports=False)
        for resource, filters in [
            ('applications', {'portfolioId': portfolio}),
            ('portfolios', {'productArea': payload['productArea']}),
        ]:
            export = await client.get('/api/reports/' + resource, headers=admin, params={**filters, 'format': 'csv'})
            assert export.status_code == 503 and export.json() == failed.json()
            assert export.headers.get('X-Correlation-ID')
            assert export.headers['content-type'].startswith('application/json')
            assert 'content-disposition' not in export.headers
            assert payload['name'] not in export.text and portfolio not in export.text
        assert await db.audit_logs.count_documents({}) == audit_before
        history = await client.get('/api/audit-logs', headers=admin, params={'pageSize': 100})
        assert history.status_code == 200 and history.json()['total'] == audit_before
        assert not any(row['entityId'] == identifier and row['action'] == 'edit' for row in history.json()['items'])
        await assert_inventory_reads(client, admin, portfolio, {**payload, **changes, 'id': identifier}, total_portfolios, exports=False)
    finally:
        await db.command({
            'collMod': 'audit_logs', 'validator': options.get('validator', {}),
            'validationLevel': options.get('validationLevel', 'strict'),
            'validationAction': options.get('validationAction', 'error'),
        })
    await assert_inventory_reads(client, admin, portfolio, {**payload, **changes, 'id': identifier}, total_portfolios)
    assert await db.audit_logs.count_documents({'entityId': ObjectId(identifier), 'action': 'edit'}) == 0
