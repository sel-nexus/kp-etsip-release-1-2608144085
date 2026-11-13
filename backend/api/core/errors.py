"""Map trust-boundary failures to a credential-safe JSON envelope."""
import logging
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError, DuplicateKeyError
from pydantic import BaseModel

logger = logging.getLogger(__name__)
class DomainError(Exception):
    """Carry only safe public error information."""
    def __init__(self, code: str, message: str, status: int, fields: dict[str, str] | None = None) -> None:
        """Retain the public contract without retaining submitted values."""
        super().__init__(message)
        self.code, self.message, self.status, self.fields = code, message, status, fields or {}
class Unauthenticated(DomainError):
    """Reject invalid identity without disclosing account existence."""
    def __init__(self) -> None:
        """Use the same response for every invalid identity."""
        super().__init__('UNAUTHENTICATED', 'Unable to authenticate', 401)
class Forbidden(DomainError):
    """Reject an authenticated action outside its policy."""
    def __init__(self) -> None:
        """Return a resource-independent denial."""
        super().__init__('FORBIDDEN', 'Permission denied', 403)

def envelope(code: str, message: str, status: int, fields: dict[str, str] | None = None, correlation: str | None = None) -> JSONResponse:
    """Serialize safe errors, with operational correlation only in a header."""
    headers = {'X-Correlation-ID': correlation} if correlation else {}
    if status == 401:
        headers['WWW-Authenticate'] = 'Bearer'
    return JSONResponse({'error': {'code': code, 'message': message, 'fields': fields or {}}}, status_code=status, headers=headers)

def register_errors(app: FastAPI) -> None:
    """Install narrow driver mappings and a safe final boundary."""
    @app.exception_handler(DomainError)
    async def domain(request: Request, exc: DomainError) -> JSONResponse:
        """Preserve the explicitly safe domain message."""
        return envelope(exc.code, exc.message, exc.status, exc.fields, getattr(exc, 'correlation', None))
    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Report declared fields only, never input, context, or extra keys."""
        allowed: dict[tuple[str, str], str] = {}
        dependant = getattr(request.scope.get('route'), 'dependant', None)
        for source in ('body', 'query', 'path', 'header', 'cookie'):
            for parameter in getattr(dependant, source + '_params', ()):
                model = parameter.type_
                if source == 'body' and isinstance(model, type) and issubclass(model, BaseModel):
                    for name, field in model.model_fields.items():
                        alias = field.alias or name
                        allowed[(source, alias)] = alias
                else:
                    allowed[(source, parameter.alias)] = parameter.alias
        fields: dict[str, str] = {}
        for failure in exc.errors():
            location = failure.get('loc', ())
            if len(location) >= 2 and failure.get('type') != 'extra_forbidden':
                name = allowed.get((location[0], location[1]))
                if name:
                    fields[name] = 'Field is required' if failure.get('type') == 'missing' else 'Invalid value'
        return envelope('VALIDATION_ERROR', 'Invalid request', 422, fields)
    @app.exception_handler(HTTPException)
    async def http(request: Request, exc: HTTPException) -> JSONResponse:
        """Keep framework errors in the application envelope."""
        return envelope('NOT_FOUND' if exc.status_code == 404 else 'INVALID_REQUEST', 'Request unavailable', exc.status_code)
    @app.exception_handler(PyMongoError)
    async def mongo(request: Request, exc: PyMongoError) -> JSONResponse:
        """Hide database endpoints and submitted records."""
        if isinstance(exc, DuplicateKeyError):
            return envelope('CONFLICT', 'Record already exists', 409)
        correlation = str(uuid4())
        logger.error('database_failure correlation=%s class=%s', correlation, type(exc).__name__)
        return envelope('DEPENDENCY_UNAVAILABLE', 'Service temporarily unavailable', 503, correlation=correlation)
    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Log only class and correlation, never exception payloads."""
        correlation = str(uuid4())
        logger.error('unexpected_failure correlation=%s class=%s', correlation, type(exc).__name__)
        return envelope('INTERNAL_ERROR', 'Request failed', 500, correlation=correlation)
