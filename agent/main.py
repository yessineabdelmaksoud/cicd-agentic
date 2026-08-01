"""
AI-CICD Agent — FastAPI Application Entry Point
v5: LangGraph (Run A / Run B split) + OpenRouter + rules-first classification
"""

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from api.routes import router
from services.metrics import init_metrics

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    log.info("agent.startup", version="5.0.0")
    init_metrics()
    yield
    log.info("agent.shutdown")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AI-CICD Embedded Agent",
    description="LangGraph-powered CI/CD repair agent using OpenRouter LLMs",
    version="5.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Include API routes
app.include_router(router)
