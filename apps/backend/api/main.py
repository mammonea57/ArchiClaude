from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health


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
    return app


app = create_app()
