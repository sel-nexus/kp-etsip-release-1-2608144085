"""Verify durable audit services, bounded history and independent CSV expectations."""
import csv
from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch
import pytest
from bson import ObjectId
from pymongo.errors import AutoReconnect
from api.core.audit import AuditService
from api.core.csv import safe_cell, csv_line
from api.core.errors import DomainError
from api.core.policy import Principal
from api.domains.audit.repository import AuditRepository
from api.domains.audit.schemas import AuditFilters
from api.domains.audit.service import AuditHistoryService, CSV_COLUMNS

@pytest.fixture
def principal():
    """Use explicit auditor authorization for service tests."""
    return Principal(ObjectId(), 'Auditor', frozenset({'view', 'export'}), (ObjectId(),), False, 'Test Auditor')

@pytest.mark.parametrize('value,expected', [(None,''), ('',''), ('=1',"'=1"), ('+1',"'+1"), ('-1',"'-1"), ('@SUM(A1)',"'@SUM(A1)"), ('text','text'), (0,'0'), ('é, "quoted"\nnext','é, "quoted"\nnext')])
def test_csv_cells_and_quoting_preserve_values(value, expected):
    assert safe_cell(value) == expected
    assert list(csv.reader(StringIO(csv_line(('details',), {'details': value}).decode('utf-8')))) == [[expected]]
    assert csv_line(('a','b')) == b'a,b\r\n'

async def test_record_unknown_actor_snapshot_is_durable_without_email(db):
    writer = AuditService(db)
    identifier = await writer.record(None, 'Unknown account', 'login', 'user', None, 'Sign-in failed')
    row = await db.audit_logs.find_one({'_id': identifier})
    assert row['userId'] is None and row['entityId'] is None and row['userName'] == 'Unknown account'
    assert row['timestamp'].tzinfo and row['createdAt'] == row['updatedAt'] == row['timestamp']
    assert 'email' not in row and row['details'] == 'Sign-in failed'

async def test_service_query_and_full_export_requery_with_and_filters(db, principal):
    repository, writer = AuditRepository(db), AuditService(db)
    service = AuditHistoryService(repository, writer)
    when = datetime(2026,1,1,tzinfo=timezone.utc)
    expected = []
    for index in range(205):
        expected.append(await repository.insert({'timestamp':when, 'userId':principal.user_id, 'userName':'=Auditor', 'action':'edit', 'entityType':'application', 'entityId':None, 'details':f'Change {index}, "safe"\nnext', 'secret':'not projected'}))
    await writer.record(ObjectId(), 'Other', 'edit', 'application', None, 'Other user')
    await writer.record(principal.user_id, principal.user_name, 'login', 'user', None, 'Other action')
    filters = AuditFilters.model_validate({'userId':str(principal.user_id), 'action':'edit', 'from':'2026-01-01T01:00:00+01:00', 'to':'2026-01-01T00:00:00Z', 'pageSize':100, 'page':2})
    page = await service.search(principal, filters)
    assert page.total == 205 and len(page.items) == 100
    assert [row.id for row in page.items] == [str(value) for value in reversed(expected)][100:200]
    output = await service.export(principal, filters)
    try:
        rows = list(csv.DictReader(StringIO(output.read().decode('utf-8'))))
    finally: output.close()
    assert len(rows) == 205 and tuple(rows[0]) == CSV_COLUMNS
    assert rows[0]['userName'] == "'=Auditor" and rows[0]['details'] == 'Change 204, "safe"\nnext'
    assert rows[0]['entityId'] == '' and rows[0]['timestamp'] == '2026-01-01T00:00:00Z'
    stored = await db.audit_logs.find_one({'_id':expected[-1]})
    assert stored['userName'] == '=Auditor' and stored['secret'] == 'not projected'
    event = await db.audit_logs.find_one({'action':'export'})
    assert event['userId'] == principal.user_id and '205 rows' in event['details']
    assert 'Change 204' not in event['details'] and 'not projected' not in event['details']

async def test_empty_search_and_export_headers_then_required_event(db, principal):
    service = AuditHistoryService(AuditRepository(db), AuditService(db))
    filters = AuditFilters(action='delete')
    assert (await service.search(principal, filters)).items == []
    output = await service.export(principal, filters)
    try: assert output.read() == b'timestamp,userId,userName,action,entityType,entityId,details\r\n'
    finally: output.close()
    assert '0 rows' in (await db.audit_logs.find_one({'action':'export'}))['details']

@pytest.mark.parametrize('role', ['Executive','Engineer','Portfolio Leader','Read Only'])
async def test_service_denies_other_roles_without_events(db, principal, role):
    service = AuditHistoryService(AuditRepository(db), AuditService(db))
    actor = replace(principal, role=role)
    for operation in (service.search, service.export):
        with pytest.raises(DomainError) as failure: await operation(actor, AuditFilters())
        assert failure.value.status == 403
    assert await db.audit_logs.count_documents({}) == 0

@pytest.mark.parametrize('permissions,method', [(frozenset(), 'search'), (frozenset({'view'}), 'export'), (frozenset({'export'}), 'search')])
async def test_service_checks_independent_permissions(db, principal, permissions, method):
    service = AuditHistoryService(AuditRepository(db), AuditService(db))
    with pytest.raises(DomainError) as failure: await getattr(service, method)(replace(principal, permissions=permissions), AuditFilters())
    assert failure.value.status == 403 and await db.audit_logs.count_documents({}) == 0

async def test_record_failure_maps_required_audit_error(db):
    writer = AuditService(db)
    async def fail(document): raise AutoReconnect('secret should never escape')
    with patch.object(writer.collection, 'insert_one', fail), pytest.raises(DomainError) as error:
        await writer.record(None, 'Unknown account', 'login', 'user', None, 'Sign-in failed')
    assert error.value.code == 'AUDIT_WRITE_FAILED' and error.value.status == 503 and error.value.correlation
    assert 'secret' not in str(error.value) and await db.audit_logs.count_documents({}) == 0

async def test_export_generation_failure_never_audits_and_closes_spool(db, principal):
    service = AuditHistoryService(AuditRepository(db), AuditService(db))
    from tempfile import SpooledTemporaryFile
    spool = SpooledTemporaryFile(mode='w+b')
    with patch('api.domains.audit.service.SpooledTemporaryFile', return_value=spool), patch('api.domains.audit.service.csv_line', side_effect=OSError('test storage fault')), pytest.raises(DomainError) as error:
        await service.export(principal, AuditFilters())
    assert error.value.status == 503 and spool.closed
    assert await db.audit_logs.count_documents({'action':'export'}) == 0

async def test_export_audit_failure_closes_generated_spool_without_success(db, principal):
    service = AuditHistoryService(AuditRepository(db), AuditService(db))
    from tempfile import SpooledTemporaryFile
    spool = SpooledTemporaryFile(mode='w+b')
    async def fail(document): raise AutoReconnect('test outage')
    with patch('api.domains.audit.service.SpooledTemporaryFile', return_value=spool), patch.object(service.audit.collection, 'insert_one', fail), pytest.raises(DomainError) as error:
        await service.export(principal, AuditFilters())
    assert error.value.code == 'AUDIT_WRITE_FAILED' and spool.closed
    assert await db.audit_logs.count_documents({}) == 0

async def test_repository_read_failure_closes_export_and_does_not_audit(db, principal):
    """Keep failed generation distinct from successful empty export."""
    service = AuditHistoryService(AuditRepository(db), AuditService(db))
    from tempfile import SpooledTemporaryFile
    spool = SpooledTemporaryFile(mode='w+b')
    with patch('api.domains.audit.service.SpooledTemporaryFile', return_value=spool), patch.object(service.repository.collection, 'find', side_effect=AutoReconnect('read fault')), pytest.raises(AutoReconnect):
        await service.export(principal, AuditFilters())
    assert spool.closed and await db.audit_logs.count_documents({}) == 0
    with patch.object(service.repository.collection, 'count_documents', side_effect=AutoReconnect('read fault')), pytest.raises(AutoReconnect):
        await service.search(principal, AuditFilters())

async def test_large_export_rolls_transient_spool_and_preserves_all_rows(db, principal):
    """Prove memory-bounded generation beyond the spool rollover threshold."""
    service = AuditHistoryService(AuditRepository(db), AuditService(db))
    now = datetime.now(timezone.utc)
    await db.audit_logs.insert_many([{'timestamp':now,'userId':principal.user_id,'userName':'Test','action':'edit','entityType':'application','entityId':None,'details':'x'*6000} for _ in range(200)])
    output = await service.export(principal, AuditFilters(action='edit', pageSize=1))
    try:
        assert output._rolled
        rows = list(csv.DictReader(StringIO(output.read().decode('utf-8'))))
        assert len(rows) == 200 and all(row['details'] == 'x'*6000 for row in rows)
    finally: output.close()
    assert '200 rows' in (await db.audit_logs.find_one({'action':'export'}))['details']
