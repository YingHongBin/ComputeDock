from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


MIN_INTERVAL_SECONDS = 5
MAX_INTERVAL_SECONDS = 3600


class ConfigurationError(ValueError):
    """Raised when required startup configuration is missing or inconsistent."""


@dataclass(frozen=True)
class AgentConfig:
    server_url: str | None
    token: str | None
    configured_container_name: str | None
    interval: int
    state_dir: Path
    test_output: Path | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="computedock-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="collect and report GPU metrics")
    run_parser.add_argument("--server-url", help="complete HTTP reporting URL")
    run_parser.add_argument("--container-name", help="persistent container identity")
    run_parser.add_argument("--interval", help="collection interval in seconds")
    run_parser.add_argument("--token", help="compute resource bearer token")
    run_parser.add_argument(
        "--test-output",
        type=Path,
        help="append JSON Lines to this file instead of making HTTP requests",
    )
    return parser


def _argument_or_environment(
    argument: str | None,
    environment: Mapping[str, str],
    variable: str,
) -> str | None:
    if argument is not None:
        return argument
    return environment.get(variable)


def resolve_config(
    arguments: argparse.Namespace,
    environment: Mapping[str, str] | None = None,
) -> AgentConfig:
    env = os.environ if environment is None else environment
    server_url = _argument_or_environment(
        arguments.server_url, env, "COMPUTEDOCK_SERVER_URL"
    )
    container_name = _argument_or_environment(
        arguments.container_name, env, "COMPUTEDOCK_CONTAINER_NAME"
    )
    interval_value = _argument_or_environment(
        arguments.interval, env, "COMPUTEDOCK_INTERVAL"
    )
    token = _argument_or_environment(arguments.token, env, "COMPUTEDOCK_TOKEN")
    test_output_value = arguments.test_output

    if interval_value is None:
        raise ConfigurationError(
            "--interval or COMPUTEDOCK_INTERVAL must be provided"
        )
    try:
        interval = int(interval_value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("interval must be an integer number of seconds") from exc
    if not MIN_INTERVAL_SECONDS <= interval <= MAX_INTERVAL_SECONDS:
        raise ConfigurationError(
            f"interval must be between {MIN_INTERVAL_SECONDS} and "
            f"{MAX_INTERVAL_SECONDS} seconds"
        )

    if test_output_value is None:
        if server_url is None:
            raise ConfigurationError(
                "--server-url or COMPUTEDOCK_SERVER_URL must be provided"
            )
        if token is None:
            raise ConfigurationError("--token or COMPUTEDOCK_TOKEN must be provided")

    state_dir_value = env.get("COMPUTEDOCK_STATE_DIR")
    if state_dir_value is None:
        raise ConfigurationError("COMPUTEDOCK_STATE_DIR must be provided")
    state_dir = Path(state_dir_value)

    return AgentConfig(
        server_url=server_url,
        token=token,
        configured_container_name=container_name,
        interval=interval,
        state_dir=state_dir,
        test_output=test_output_value,
    )


def parse_config(
    argv: Sequence[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> tuple[argparse.ArgumentParser, AgentConfig]:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    return parser, resolve_config(arguments, environment)
