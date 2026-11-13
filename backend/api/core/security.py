"""Offload bcrypt and issue subject-only, expiring bearer identities."""
import asyncio
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from jose import jwt, JWTError
from passlib.context import CryptContext
from api.core.config import Settings
from api.core.errors import Unauthenticated

password_context = CryptContext(schemes=['bcrypt'], deprecated='auto', bcrypt__truncate_error=True)
async def hash_password(password: str) -> str:
    """Hash the full supported bcrypt credential outside the event loop."""
    return await asyncio.to_thread(password_context.hash, password)
async def verify_password(password: str, stored_hash: str) -> bool:
    """Fail closed for damaged hashes and bcrypt truncation aliases."""
    if len(password.encode('utf-8')) > 72:
        return False
    try:
        return await asyncio.to_thread(password_context.verify, password, stored_hash)
    except (ValueError, TypeError):
        return False

def create_access_token(user_id: ObjectId, settings: Settings, now: datetime | None = None) -> str:
    """Sign subject and mandatory expiration/issuer claims, not permissions."""
    issued = now or datetime.now(timezone.utc)
    return jwt.encode({'sub': str(user_id), 'iat': issued, 'exp': issued + timedelta(hours=settings.JWT_EXPIRY_HOURS), 'iss': settings.JWT_ISSUER}, settings.JWT_SECRET.get_secret_value(), algorithm='HS256')

def verify_access_token(token: str, settings: Settings) -> ObjectId:
    """Require signature, expiration, issuer, and a valid persisted subject ID."""
    try:
        claims = jwt.decode(token, settings.JWT_SECRET.get_secret_value(), algorithms=['HS256'], issuer=settings.JWT_ISSUER, options={'require_exp': True, 'require_iat': True, 'require_sub': True, 'require_iss': True})
        subject = claims['sub']
        if not isinstance(subject, str) or not ObjectId.is_valid(subject):
            raise Unauthenticated()
        return ObjectId(subject)
    except (JWTError, ValueError, TypeError, KeyError) as exc:
        raise Unauthenticated() from exc
