from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from agent.core.runtime_paths import apply_runtime_env, configure_standard_streams

configure_standard_streams()

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent.core.runtime_layout import APP_ROOT, PROJECT_ROOT
from agent.server.routes import chat, files, meta, projects, runtime, sessions, settings, users
from agent.server.deps import agent_manager
from agent.tools.browser_harness_runtime import shutdown_browser_harness_runtime


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await asyncio.to_thread(agent_manager.release_all)
    await asyncio.to_thread(shutdown_browser_harness_runtime, PROJECT_ROOT)


def create_app() -> FastAPI:
    apply_runtime_env(PROJECT_ROOT)
    app = FastAPI(title="agent-alpha web", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects.router)
    app.include_router(sessions.router)
    app.include_router(chat.router)
    app.include_router(settings.router)
    app.include_router(users.router)
    app.include_router(files.router)
    app.include_router(meta.router)
    app.include_router(runtime.router)

    @app.get("/api/health")
    def health():
        return {"ok": True, "project_root": str(PROJECT_ROOT)}

    dist = APP_ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()


def main() -> None:
    uvicorn.run("agent.server.app:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()
