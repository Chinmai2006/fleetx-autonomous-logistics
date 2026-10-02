from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.agentic import router as agentic_router
from app.api.health import router as health_router
from app.api.agents import router as agents_router
from app.api.tasks import router as tasks_router
from app.api.operations import router as operations_router
from app.api.demo import router as demo_router
from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from app.services.agentic_orchestrator import agentic_orchestrator
from app.services.agent_manager import dynamic_agent_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks
    platform_registry_service.start()
    task_coordination_service.start()
    agentic_orchestrator.start()
    yield
    # Shutdown tasks
    agentic_orchestrator.stop()
    dynamic_agent_manager.shutdown()
    task_coordination_service.stop()
    platform_registry_service.stop()


app = FastAPI(
    title=settings.APP_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register health check router under versioned API and root health alias
app.include_router(health_router, prefix=settings.API_V1_STR, tags=["Health"])
app.include_router(health_router, tags=["Health Root"])
app.include_router(agents_router, prefix=settings.API_V1_STR, tags=["Agents"])
app.include_router(tasks_router, prefix=settings.API_V1_STR, tags=["Tasks"])
app.include_router(agentic_router, prefix=settings.API_V1_STR, tags=["Agentic AI"])
app.include_router(operations_router, prefix=settings.API_V1_STR, tags=["Operations"])
app.include_router(demo_router, prefix=settings.API_V1_STR, tags=["Demo"])


@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "docs": "/docs",
        "health": f"{settings.API_V1_STR}/health"
    }
