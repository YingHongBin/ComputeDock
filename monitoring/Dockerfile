FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS backend-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build/backend
COPY backend/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip python -m venv /opt/monitoring-venv \
    && /opt/monitoring-venv/bin/pip install -r requirements.txt
COPY backend/pyproject.toml ./
COPY backend/src/ ./src/
RUN /opt/monitoring-venv/bin/pip install --no-deps .

FROM python:3.13-slim-bookworm

ENV PATH=/opt/monitoring-venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MONITORING_FRONTEND_DIR=/opt/computedock-monitor/frontend

RUN useradd --system --user-group --home-dir /opt/computedock-monitor --create-home computedock-monitor
COPY --from=backend-builder /opt/monitoring-venv /opt/monitoring-venv
COPY backend/alembic.ini /opt/computedock-monitor/alembic.ini
COPY backend/alembic /opt/computedock-monitor/alembic
COPY --from=frontend-builder /build/frontend/dist /opt/computedock-monitor/frontend
RUN chown -R computedock-monitor:computedock-monitor /opt/computedock-monitor

USER computedock-monitor
WORKDIR /opt/computedock-monitor
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn computedock_monitor.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
