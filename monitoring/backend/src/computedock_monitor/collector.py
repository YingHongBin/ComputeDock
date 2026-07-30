from __future__ import annotations

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import get_db
from .routers import agent

app = FastAPI(title="ComputeDock Collector", version="1.0.0")
app.include_router(agent.router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
