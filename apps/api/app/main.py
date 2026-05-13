from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging, log
from app.routers import (
    agents,
    api_keys,
    auth_oauth,
    calls,
    catalog,
    console,
    knowledge_bases,
    phone_numbers,
    squads,
    telnyx_media_ws,
    tools,
    web_call_ws,
    webhooks,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info("api.start", env=settings.env)
    yield
    log.info("api.stop")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Voice 2.0 API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(agents.router)
    app.include_router(tools.router)
    app.include_router(phone_numbers.router)
    app.include_router(knowledge_bases.router)
    app.include_router(squads.router)
    app.include_router(calls.router)
    app.include_router(web_call_ws.router)
    app.include_router(telnyx_media_ws.router)
    app.include_router(webhooks.router)
    app.include_router(auth_oauth.router)
    app.include_router(api_keys.router)
    app.include_router(console.router)
    app.include_router(catalog.router)

    return app


app = create_app()
