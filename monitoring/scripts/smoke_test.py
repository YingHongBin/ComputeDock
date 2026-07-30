#!/usr/bin/env python3
"""Run a destructive-to-test-data-only smoke flow against a live monitoring app."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证监控应用完整 API 流程")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", required=True)
    return parser.parse_args()


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookies),
        )

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        expected: int = 200,
    ) -> object:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        try:
            response = self.opener.open(request, timeout=10)
            status_code = response.status
            content = response.read()
        except urllib.error.HTTPError as error:
            status_code = error.code
            content = error.read()
        if status_code != expected:
            raise RuntimeError(
                f"{method} {path}: expected {expected}, got {status_code}: "
                f"{content.decode(errors='replace')}"
            )
        return None if not content else json.loads(content)


def sample(container_name: str, collected_at: datetime, utilization: int = 42) -> dict[str, object]:
    return {
        "container_name": container_name,
        "collected_at": collected_at.isoformat().replace("+00:00", "Z"),
        "gpus": [
            {
                "gpuid": "GPU-SMOKE-SHARED",
                "memory_used": 4096,
                "memory_total": 24576,
                "utilization": utilization,
            }
        ],
    }


def main() -> int:
    args = parse_args()
    client = Client(args.base_url)
    login = client.request(
        "POST",
        "/api/v1/auth/login",
        {"username": args.username, "password": args.password},
    )
    assert isinstance(login, dict)
    csrf_headers = {"X-CSRF-Token": str(login["csrf_token"])}
    suffix = uuid.uuid4().hex[:8]
    resource = client.request(
        "POST",
        "/api/v1/resources",
        {"name": f"smoke-{suffix}", "gpu_model": "Mock A100", "gpu_count": 1},
        csrf_headers,
        201,
    )
    assert isinstance(resource, dict)
    resource_id = str(resource["id"])
    token = str(resource["token"])
    agent_headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=2)

    first = sample("smoke-worker-1", now)
    accepted = client.request("POST", "/api/v1/agent/samples", first, agent_headers)
    duplicate = client.request("POST", "/api/v1/agent/samples", first, agent_headers)
    assert isinstance(accepted, dict) and accepted["status"] == "accepted"
    assert isinstance(duplicate, dict) and duplicate["status"] == "duplicate"
    client.request(
        "POST", "/api/v1/agent/samples", sample("smoke-worker-1", now, 43), agent_headers, 409
    )
    client.request(
        "POST",
        "/api/v1/agent/samples",
        sample("smoke-worker-2", now + timedelta(seconds=1), 55),
        agent_headers,
    )

    current = client.request("GET", f"/api/v1/resources/{resource_id}")
    assert isinstance(current, dict) and current["allocated_gpu_count"] == 1
    containers = client.request("GET", f"/api/v1/resources/{resource_id}/containers")
    assert isinstance(containers, list) and len(containers) == 2
    worker_1 = next(item for item in containers if item["name"] == "smoke-worker-1")
    chart = client.request(
        "GET",
        f"/api/v1/resources/{resource_id}/containers/{worker_1['id']}/chart?range=1h",
    )
    assert isinstance(chart, dict) and chart["series"][0]["shared"] is True

    client.request(
        "DELETE",
        f"/api/v1/resources/{resource_id}/containers/{worker_1['id']}",
        headers=csrf_headers,
        expected=204,
    )
    client.request(
        "POST",
        "/api/v1/agent/samples",
        sample("smoke-worker-1", now + timedelta(seconds=2), 60),
        agent_headers,
    )
    regenerated = client.request("GET", f"/api/v1/resources/{resource_id}/containers")
    assert isinstance(regenerated, list)
    assert next(item for item in regenerated if item["name"] == "smoke-worker-1")["generation"] == 2

    client.request(
        "DELETE", f"/api/v1/resources/{resource_id}", headers=csrf_headers, expected=204
    )
    client.request(
        "POST",
        "/api/v1/agent/samples",
        sample("smoke-worker-1", now + timedelta(seconds=3), 70),
        agent_headers,
        401,
    )
    print("完整 API 冒烟流程通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

