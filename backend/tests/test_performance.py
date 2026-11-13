"""Measure the proposed few-hundred-row engineering scenario without SLA claims."""
import asyncio
import csv
from io import StringIO
import json
import math
import statistics
import time
from pathlib import Path
from datetime import datetime, timezone
from bson import ObjectId
from api.core.security import create_access_token


async def test_300_rows_scoped_paging_dashboard_and_csv(client, db, identity, app):
    """Check 300 records under 20 concurrent readers and capture query evidence."""
    user, _ = identity
    now = datetime.now(timezone.utc)
    portfolio = ObjectId()
    await db.portfolios.insert_one({'_id': portfolio, 'name': 'Load fixture', 'ownerName': 'Fake owner', 'description': 'Synthetic', 'productArea': 'Synthetic', 'status': 'Active', 'createdAt': now, 'updatedAt': now})
    await db.users.update_one({'_id': user['_id']}, {'$set': {'portfolioAccess': [portfolio]}})
    documents = [{'_id': ObjectId(), 'name': f'Synthetic {index:03}', 'description': 'Synthetic', 'portfolioId': portfolio, 'productArea': 'Synthetic', 'businessOwner': 'Fake', 'technologyOwner': 'Fake', 'etsOwner': 'Fake', 'criticality': 'High', 'tier': 2, 'lifecycleStatus': 'Active', 'technologyStack': 'Python', 'repositoryUrl': None, 'pipelineUrl': None, 'applicationHealthScore': 80, 'qualityScore': 75, 'automationCoverage': 60, 'unitTestCoverage': 70, 'openDefects': 4, 'openCriticalDefects': 1, 'riskLevel': 'High', 'createdAt': now, 'updatedAt': now} for index in range(300)]
    await db.applications.insert_many(documents)
    headers = {'Authorization': 'Bearer ' + create_access_token(user['_id'], app.state.settings)}
    async def read(index):
        """Measure one authorized bounded list and dashboard request pair."""
        start = time.perf_counter()
        listing = await client.get('/api/applications', headers=headers, params={'page': index % 3 + 1, 'pageSize': 100})
        dashboard = await client.get('/api/dashboard/executive', headers=headers)
        elapsed = time.perf_counter() - start
        assert listing.status_code == dashboard.status_code == 200
        assert listing.json()['total'] == 300 and len(listing.json()['items']) == 100
        assert dashboard.json()['metrics']['enterpriseQualityScore'] == 75
        assert dashboard.json()['metrics']['totalApplications'] == 300
        return elapsed
    durations = await asyncio.gather(*(read(index) for index in range(20)))
    export = await client.get('/api/reports/applications?format=csv', headers=headers)
    assert export.status_code == 200 and len(export.text.splitlines()) == 301
    plan = await db.command({'explain': {'find': 'applications', 'filter': {'portfolioId': portfolio}, 'limit': 100}, 'verbosity': 'queryPlanner'})
    evidence = {'scenario': '300 applications, 20 concurrent in-process authenticated readers', 'p50_seconds': statistics.median(durations), 'p95_seconds': sorted(durations)[math.ceil(.95 * len(durations)) - 1], 'errors': 0, 'query_plan': plan['queryPlanner']['winningPlan'], 'long_steady_load': 'not executed; proposed HLD gate, not product SLA'}
    Path('performance-evidence.json').write_text(json.dumps(evidence, default=str, indent=2), encoding='utf-8')


async def test_20_concurrent_readers_exclude_hidden_rows_and_deny_live_reductions(client, db, identity, app) -> None:
    """Keep real Mongo scope and permission boundaries intact under concurrent reads."""
    user, _ = identity
    now = datetime.now(timezone.utc)
    visible, hidden = ObjectId(), ObjectId()
    await db.portfolios.insert_many([
        {'_id': identifier, 'name': name, 'ownerName': 'Fake owner', 'description': 'Synthetic',
         'productArea': 'Synthetic', 'status': 'Active', 'createdAt': now, 'updatedAt': now}
        for identifier, name in [(visible, 'Visible load portfolio'), (hidden, 'Hidden load portfolio')]
    ])
    await db.users.update_one({'_id': user['_id']}, {'$set': {'portfolioAccess': [visible]}})
    documents = [
        {'_id': ObjectId(), 'name': f'{label} load {index:03}', 'description': 'Synthetic',
         'portfolioId': portfolio, 'productArea': 'Synthetic', 'businessOwner': 'Fake',
         'technologyOwner': 'Fake', 'etsOwner': 'Fake', 'criticality': 'High', 'tier': 2,
         'lifecycleStatus': 'Active', 'technologyStack': 'Python', 'repositoryUrl': None,
         'pipelineUrl': None, 'applicationHealthScore': 80 if portfolio == visible else 0,
         'qualityScore': 75 if portfolio == visible else 0,
         'automationCoverage': 60 if portfolio == visible else 0, 'unitTestCoverage': 70,
         'openDefects': 4, 'openCriticalDefects': 1 if portfolio == visible else 99,
         'riskLevel': 'High' if portfolio == visible else 'Low', 'createdAt': now, 'updatedAt': now}
        for portfolio, label in [(visible, 'Visible'), (hidden, 'Hidden')]
        for index in range(300)
    ]
    await db.applications.insert_many(documents)
    assert await db.applications.count_documents({'portfolioId': visible}) == 300
    assert await db.applications.count_documents({'portfolioId': hidden}) == 300
    visible_ids = {str(row['_id']) for row in documents if row['portfolioId'] == visible}
    hidden_ids = {str(row['_id']) for row in documents if row['portfolioId'] == hidden}
    headers = {'Authorization': 'Bearer ' + create_access_token(user['_id'], app.state.settings)}
    read_paths = ['/api/applications', '/api/portfolios', '/api/reports/applications',
                  '/api/reports/portfolios', '/api/dashboard/executive']
    export_paths = ['/api/applications', '/api/reports/applications', '/api/reports/portfolios']

    async def read(index: int) -> None:
        """Verify each list, report, complete CSV and metric excludes hidden facts."""
        for path in read_paths[:-1]:
            is_portfolio = path.endswith('portfolios')
            response = await client.get(path, headers=headers, params={
                'page': 1 if is_portfolio else index % 3 + 1, 'pageSize': 100,
            })
            assert response.status_code == 200
            result = response.json()
            assert result['total'] == (1 if is_portfolio else 300)
            assert len(result['items']) == (1 if is_portfolio else 100)
            assert 'Hidden' not in response.text and str(hidden) not in response.text
            if is_portfolio:
                assert result['items'][0]['id'] == str(visible)
                assert result['items'][0]['applicationCount'] == 300
                assert result['items'][0]['qualityScore'] == 75
            else:
                ids = {row['id'] for row in result['items']}
                assert len(ids) == 100 and ids <= visible_ids and ids.isdisjoint(hidden_ids)
                assert all(row['portfolioId'] == str(visible) for row in result['items'])
        dashboard = await client.get('/api/dashboard/executive', headers=headers)
        assert dashboard.status_code == 200
        assert dashboard.json() == {
            'metrics': {'enterpriseQualityScore': 75, 'averageApplicationHealthScore': 80,
                        'automationMaturityScore': 60, 'openCriticalDefects': 300,
                        'applicationsAtRisk': 300, 'totalApplications': 300, 'totalPortfolios': 1},
            'portfolioComparisons': [{'portfolioId': str(visible), 'name': 'Visible load portfolio',
                                     'qualityScore': 75, 'applicationsAtRisk': 300}],
        }
        for path in export_paths:
            exported = await client.get(path, headers=headers, params={
                'format': 'csv', 'page': 99, 'pageSize': 1,
            })
            assert exported.status_code == 200
            rows = list(csv.DictReader(StringIO(exported.text)))
            assert 'Hidden' not in exported.text and str(hidden) not in exported.text
            if path.endswith('portfolios'):
                assert len(rows) == 1 and rows[0]['id'] == str(visible)
                assert rows[0]['applicationCount'] == '300' and rows[0]['qualityScore'] == '75'
            else:
                assert len(rows) == 300
                assert {row['id'] for row in rows} == visible_ids
                assert all(row['portfolioId'] == str(visible) for row in rows)

    await asyncio.gather(*(read(index) for index in range(20)))
    export_filter = {'action': 'export', 'userId': user['_id']}
    authorized_exports = await db.audit_logs.find(export_filter).sort('_id', 1).to_list(None)
    assert len(authorized_exports) == 60

    async def denied(paths: list[str], export: bool = False) -> None:
        """Reuse the already-issued token and require data-free permission denials."""
        for path in paths:
            response = await client.get(path, headers=headers, params={'format': 'csv'} if export else {})
            assert response.status_code == 403 and response.json()['error']['code'] == 'FORBIDDEN'
            assert response.headers['content-type'].startswith('application/json')
            assert 'content-disposition' not in response.headers
            assert 'items' not in response.json() and 'metrics' not in response.json()
            assert 'Visible load' not in response.text and 'Hidden load' not in response.text
            assert str(visible) not in response.text and str(hidden) not in response.text

    await db.roles.update_one({'name': user['role']}, {'$pull': {'permissions': 'export'}})
    await asyncio.gather(*(denied(export_paths, export=True) for _ in range(20)))
    assert await db.audit_logs.find(export_filter).sort('_id', 1).to_list(None) == authorized_exports
    # Export-only reduction must not accidentally deny ordinary reads.
    for path in read_paths:
        assert (await client.get(path, headers=headers)).status_code == 200
    await db.roles.update_one({'name': user['role']}, {'$pull': {'permissions': 'view'}})
    await asyncio.gather(*(denied(read_paths) for _ in range(20)),
                         *(denied(export_paths, export=True) for _ in range(20)))
    assert await db.audit_logs.find(export_filter).sort('_id', 1).to_list(None) == authorized_exports
