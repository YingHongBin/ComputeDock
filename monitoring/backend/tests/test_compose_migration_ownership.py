from pathlib import Path

COMPOSE_FILE = Path(__file__).parents[2] / "docker-compose.yml"
DOCKERFILE = Path(__file__).parents[2] / "Dockerfile"


def _service_block(compose: str, service: str, next_service: str) -> str:
    return compose.split(f"\n  {service}:\n", 1)[1].split(f"\n  {next_service}:\n", 1)[0]


def test_app_owns_database_migrations() -> None:
    compose = COMPOSE_FILE.read_text()
    collector = _service_block(compose, "collector", "app")
    app = _service_block(compose, "app", "worker")

    assert "alembic upgrade head" not in collector
    assert "alembic upgrade head" in app
    assert "exec uvicorn computedock_monitor.main:app" in app


def test_migration_files_are_only_packaged_in_app_image() -> None:
    dockerfile = DOCKERFILE.read_text()
    runtime_stages, app_stage = dockerfile.split("FROM runtime-base AS app", 1)

    assert "COPY backend/alembic" not in runtime_stages
    assert "backend/alembic.ini" in app_stage
    assert "backend/alembic " in app_stage


def test_services_can_be_updated_independently() -> None:
    compose = COMPOSE_FILE.read_text()
    collector = _service_block(compose, "collector", "app")
    app = _service_block(compose, "app", "worker")
    worker = compose.split("\n  worker:\n", 1)[1].split("\nvolumes:\n", 1)[0]

    for service in (collector, app, worker):
        assert "database:\n        condition: service_healthy" in service

    assert "target: collector" in collector
    assert "target: app" in app
    assert "target: worker" in worker
    assert "COLLECTOR_IMAGE_TAG" in collector
    assert "APP_IMAGE_TAG" in app
    assert "WORKER_IMAGE_TAG" in worker
    assert "http://127.0.0.1:8000/api/health" in app
