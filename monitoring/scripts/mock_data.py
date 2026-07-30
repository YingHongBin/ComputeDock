#!/usr/bin/env python3
"""Generate deterministic recent GPU samples through the real Agent API."""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="向监控应用生成模拟 GPU 上报数据")
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000/api/v1/agent/samples",
        help="完整的 Agent 数据上报地址",
    )
    parser.add_argument("--token", required=True, help="算力资源卡片上显示的 Token")
    parser.add_argument("--containers", type=int, default=2, help="模拟容器数量")
    parser.add_argument("--gpus-per-container", type=int, default=2, help="每个容器 GPU 数量")
    parser.add_argument("--hours", type=float, default=1.0, help="生成最近多少小时，最大 24")
    parser.add_argument("--interval", type=int, default=60, help="样本间隔秒数")
    parser.add_argument("--gap-every", type=int, default=11, help="每 N 个周期跳过一次，0 表示不跳过")
    parser.add_argument("--zero-every", type=int, default=7, help="每 N 个周期生成真实零值，0 表示不生成")
    parser.add_argument("--shared-gpu", action="store_true", help="让每个容器共享第一张 GPU UUID")
    return parser.parse_args()


def validate(args: argparse.Namespace) -> None:
    if args.containers < 1 or args.gpus_per_container < 1:
        raise ValueError("containers 和 gpus-per-container 必须大于 0")
    if not 0 < args.hours <= 24:
        raise ValueError("hours 必须大于 0 且不超过 24")
    if args.interval < 1:
        raise ValueError("interval 必须大于 0")


def gpu_id(container_index: int, gpu_index: int, shared: bool) -> str:
    if shared and gpu_index == 0:
        return "GPU-MOCK-SHARED-0000"
    return f"GPU-MOCK-{container_index + 1:02d}-{gpu_index + 1:02d}"


def send(server_url: str, token: str, payload: dict[str, object]) -> str:
    request = urllib.request.Request(
        server_url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    hostname = urllib.parse.urlparse(server_url).hostname
    opener = (
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if hostname in {"localhost", "127.0.0.1", "::1"}
        else urllib.request.build_opener()
    )
    with opener.open(request, timeout=10) as response:
        return response.read().decode("utf-8")


def main() -> int:
    args = parse_args()
    try:
        validate(args)
    except ValueError as error:
        print(f"参数错误：{error}", file=sys.stderr)
        return 2

    end = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=1)
    points = max(1, int(args.hours * 3600 / args.interval))
    start = end - timedelta(seconds=(points - 1) * args.interval)
    sent = 0
    for point_index in range(points):
        if args.gap_every and point_index and point_index % args.gap_every == 0:
            continue
        collected_at = start + timedelta(seconds=point_index * args.interval)
        for container_index in range(args.containers):
            metrics = []
            for index in range(args.gpus_per_container):
                zero = bool(args.zero_every and point_index % args.zero_every == 0)
                wave = (math.sin((point_index + container_index + index) / 4) + 1) / 2
                utilization = 0 if zero else round(10 + wave * 82)
                total = 24 * 1024
                used = 0 if zero else round(total * (0.12 + wave * 0.75))
                metrics.append(
                    {
                        "gpuid": gpu_id(container_index, index, args.shared_gpu),
                        "memory_used": used,
                        "memory_total": total,
                        "utilization": utilization,
                    }
                )
            payload = {
                "container_name": f"mock-container-{container_index + 1:02d}",
                "collected_at": collected_at.isoformat().replace("+00:00", "Z"),
                "gpus": metrics,
            }
            try:
                send(args.server_url, args.token, payload)
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                print(f"上报失败 HTTP {error.code}: {detail}", file=sys.stderr)
                return 1
            except OSError as error:
                print(f"上报失败：{error}", file=sys.stderr)
                return 1
            sent += 1
    print(f"已生成 {sent} 个批次，时间范围 {start.isoformat()} 至 {end.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
