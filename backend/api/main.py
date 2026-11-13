"""Create the session and profile API and initialize its real Mongo lifecycle."""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pymongo.errors import PyMongoError
from api.core.config import Settings
from api.core.database import database_lifespan
from api.core.errors import register_errors, DomainError
from api.domains.auth.router import router
from api.domains.auth.profile_router import router as profile_router
from api.domains.portfolios.router import router as portfolio_router
from api.domains.applications.router import router as application_router

def create_app(settings: Settings | None = None) -> FastAPI:
    """Compose implemented routers only, with validated startup configuration."""
    application = FastAPI(title='KP ETSIP Release 1', version='1.0.0', description='Platform Foundation local session API', lifespan=database_lifespan)
    application.state.settings = settings
    # Validate settings before accepting traffic; no import-time database connection.
    configuration = settings or Settings()
    application.state.settings = configuration
    application.add_middleware(CORSMiddleware, allow_origins=configuration.cors_origins, allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Authorization', 'Content-Type'])
    register_errors(application)
    application.include_router(router)
    application.include_router(profile_router)
    application.include_router(portfolio_router)
    application.include_router(application_router)
    @application.middleware('http')
    async def private_api(request: Request, call_next):
        """Prevent shared caches from retaining authenticated responses."""
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response
    @application.get('/api/health', summary='Check database readiness')
    async def health(request: Request) -> dict[str, str]:
        """Advertise readiness only while the required database responds."""
        try:
            await request.app.state.database.command('ping')
        except PyMongoError as exc:
            raise DomainError('DEPENDENCY_UNAVAILABLE', 'Service temporarily unavailable', 503) from exc
        return {'status': 'ok'}
    return application

app = create_app()
