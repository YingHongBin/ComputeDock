from computedock_monitor.collector import app as collector_app
from computedock_monitor.main import app as management_app


def route_paths(app) -> set[str]:
    return set(app.openapi()["paths"])


def test_collector_owns_agent_upload_endpoint() -> None:
    assert "/api/v1/agent/samples" in route_paths(collector_app)
    assert "/api/v1/agent/samples" not in route_paths(management_app)


def test_management_routes_are_not_exposed_by_collector() -> None:
    assert "/api/v1/resources" in route_paths(management_app)
    assert "/api/v1/resources" not in route_paths(collector_app)
