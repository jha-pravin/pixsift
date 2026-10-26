"""App factory: engine objects, security middleware, API routers and the built UI.
Binds to localhost only; files are served by id, never by raw path."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import Settings
from .db import Database
from .images_api import router as images_router
from .people_api import router as people_router
from .pipeline import Pipeline
from .security import AccessGuard
from .system_api import router as system_router
from .volumes import DriveWatcher


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    pipeline = Pipeline(db, settings)
    watcher = DriveWatcher(db, lambda roots: pipeline.start(roots))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.watch_drives:
            watcher.start()
        # Resume analysis that was interrupted (app quit, laptop slept, drive unplugged) without waiting
        # for the next scan.
        if pipeline.models.status()["ready"] and db.query_one(
            f"SELECT 1 FROM images i WHERE {Pipeline._PENDING_WHERE} LIMIT 1"
        ):
            pipeline.start(None)
        yield
        watcher.stop()

    app = FastAPI(title="PixSift", version=__version__, lifespan=lifespan)
    app.state.db, app.state.pipeline, app.state.settings, app.state.watcher = db, pipeline, settings, watcher
    # Starlette runs the last-added middleware first: Host check (DNS rebinding), then the access guard.
    app.add_middleware(AccessGuard, token=settings.token)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    for router in (system_router, images_router, people_router):
        app.include_router(router, prefix="/api")

    # Serve the built UI when present, so a single process runs the whole app.
    dist = _ui_dist()
    if dist:
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
    return app


def _ui_dist() -> Path | None:
    candidates = [Path(__file__).resolve().parents[2] / "frontend" / "dist"]
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        candidates.insert(0, Path(getattr(sys, "_MEIPASS", "")) / "ui")
    return next((p for p in candidates if p.is_dir()), None)
