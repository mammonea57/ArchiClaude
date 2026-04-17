from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health
from api.routes.admin import flags as admin_flags
from api.routes.agency import router as agency_router
from api.routes.parcels import router as parcels_router
from api.routes.plu import router as plu_router
from api.routes.projects import router as projects_router
from api.routes.rag import router as rag_router
from api.routes.reports import router as reports_router
from api.routes.site import router as site_router
from api.routes.versions import router as versions_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="ArchiClaude API",
        version="0.1.0",
        description="API faisabilité architecturale IDF",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(admin_flags.router, prefix="/api/v1")
    app.include_router(agency_router, prefix="/api/v1")
    app.include_router(parcels_router, prefix="/api/v1")
    app.include_router(plu_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(rag_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(site_router, prefix="/api/v1")
    app.include_router(versions_router, prefix="/api/v1")
    return app


app = create_app()
