from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal
from .models import Admin
from .proxy_prefix import (
    FORWARDED_PREFIX_HEADER,
    inject_base_href,
    normalize_forwarded_prefix,
    request_prefix,
)
from .routers import agent, auth, resources
from .security import hash_password, utcnow


def ensure_initial_admin() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(Admin).limit(1)) is not None:
            return
        now = utcnow()
        db.add(
            Admin(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_initial_admin()
    yield


settings = get_settings()
app = FastAPI(title="ComputeDock Monitor", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def forwarded_prefix_middleware(request: Request, call_next):
    try:
        request.state.forwarded_prefix = normalize_forwarded_prefix(
            request.headers.get(FORWARDED_PREFIX_HEADER)
        )
    except ValueError:
        return JSONResponse({"detail": "invalid X-Forwarded-Prefix"}, status_code=400)
    return await call_next(request)


if settings.allowed_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(resources.router)
app.include_router(agent.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


frontend_dir: Path = settings.frontend_dir
assets_dir = frontend_dir / "assets"
if assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str, request: Request):
    if path.startswith("api/"):
        return JSONResponse({"detail": "not found"}, status_code=404)
    index = frontend_dir / "index.html"
    if index.is_file():
        html = inject_base_href(index.read_text(encoding="utf-8"), request_prefix(request))
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-cache",
                "Vary": FORWARDED_PREFIX_HEADER,
            },
        )
    return JSONResponse({"message": "frontend is not built; run Vite on port 5173 for development"})
