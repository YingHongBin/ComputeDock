from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from .config import get_settings
from .database import SessionLocal
from .models import Admin, EmailActionToken, User
from .notifications import action_url, enqueue_notification, issue_action_token
from .proxy_prefix import (
    FORWARDED_PREFIX_HEADER,
    inject_base_href,
    normalize_forwarded_prefix,
    request_prefix,
)
from .routers import auth, compute_requests, projects, resources, users
from .security import hash_password, utcnow


def ensure_initial_admin() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        now = utcnow()
        admin = db.scalar(
            select(Admin).where(func.lower(Admin.username) == settings.admin_username.lower())
        )
        user = db.scalar(
            select(User).where(func.lower(User.username) == settings.admin_username.lower())
        )
        if user is None:
            if admin is None:
                admin = Admin(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    created_at=now,
                    updated_at=now,
                )
                db.add(admin)
                db.flush()
            user = User(
                id=admin.id,
                username=settings.admin_username,
                full_name=settings.admin_username,
                password_hash=admin.password_hash,
                role="admin",
                status="active",
                must_bind_email=True,
                created_at=admin.created_at,
                updated_at=admin.updated_at,
            )
            db.add(user)
            db.flush()
        if settings.admin_email and user.email is None:
            user.email = settings.admin_email.strip().lower()
            user.must_bind_email = True
            user.updated_at = now
        if user.email and user.email_verified_at is None:
            pending_token = db.scalar(
                select(EmailActionToken.id).where(
                    EmailActionToken.user_id == user.id,
                    EmailActionToken.purpose == "email_change",
                    EmailActionToken.pending_email == user.email,
                    EmailActionToken.consumed_at.is_(None),
                    EmailActionToken.expires_at > now,
                )
            )
            if pending_token is None:
                token, secret = issue_action_token(
                    db,
                    purpose="email_change",
                    user_id=user.id,
                    pending_email=user.email,
                )
                enqueue_notification(
                    db,
                    idempotency_key=f"legacy-admin-email:{token.id}",
                    template="email_change_verify",
                    to_address=user.email,
                    payload={
                        "full_name": user.full_name,
                        "action_url": action_url(settings, "/verify-new-email", secret),
                        "expires_hours": 24,
                    },
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
app.include_router(users.router)
app.include_router(projects.router)
app.include_router(compute_requests.router)
app.include_router(resources.router)


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
