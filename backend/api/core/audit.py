"""Persist synchronous audit evidence before reporting successful actions."""
import logging
from uuid import uuid4
from datetime import datetime, timezone
from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError
from api.core.errors import DomainError
from api.domains.audit.repository import AuditRepository

logger = logging.getLogger(__name__)
class AuditService:
    """Write durable actor snapshots and expose reconciliation on failure."""
    def __init__(self, database: AsyncDatabase) -> None:
        """Use the application pooled collection."""
        self.repository = AuditRepository(database)
        self.collection = self.repository.collection
    async def record(self, user_id: ObjectId | None, user_name: str, action: str, entity_type: str, entity_id: ObjectId | None, details: str) -> ObjectId:
        """Require a safe call-site summary and never retry ambiguous writes."""
        now = datetime.now(timezone.utc)
        document = {'timestamp': now, 'userId': user_id, 'userName': user_name, 'action': action, 'entityType': entity_type, 'entityId': entity_id, 'details': details, 'createdAt': now, 'updatedAt': now}
        try:
            return await self.repository.insert(document)
        except PyMongoError as exc:
            correlation = str(uuid4())
            logger.error('audit_reconciliation_required correlation=%s entity=%s class=%s', correlation, entity_id, type(exc).__name__)
            error = DomainError('AUDIT_WRITE_FAILED', 'Required audit could not be recorded', 503)
            error.correlation = correlation
            raise error from exc
