from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from collections.abc import Mapping, Sequence

from .agent import Agent
from .collector import NvmlCollector
from .config import ConfigurationError, build_parser, resolve_config
from .identity import IdentityError, load_or_create_identity
from .reporting import HttpReporter, JsonLinesReporter


LOGGER = logging.getLogger("computedock_agent")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def install_signal_handlers(stop_event: threading.Event) -> None:
    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)


def gpu_collection_is_disabled(environment: Mapping[str, str]) -> bool:
    visible_devices = environment.get("NVIDIA_VISIBLE_DEVICES")
    return visible_devices is not None and (
        visible_devices.strip().lower() in {"", "none", "void"}
    )


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        config = resolve_config(arguments)
        container_name = load_or_create_identity(
            config.state_dir, config.configured_container_name
        )
    except (ConfigurationError, IdentityError) as exc:
        parser.error(str(exc))

    stop_event = threading.Event()
    install_signal_handlers(stop_event)
    collector = NvmlCollector(disabled=gpu_collection_is_disabled(os.environ))
    if config.test_output is not None:
        reporter = JsonLinesReporter(config.test_output)
    else:
        # resolve_config guarantees both values in HTTP mode.
        reporter = HttpReporter(config.server_url or "", config.token or "")
    agent = Agent(
        container_name=container_name,
        interval=config.interval,
        collector=collector,
        reporter=reporter,
        stop_event=stop_event,
        token=config.token,
        logger=LOGGER,
    )
    agent.run()
    return 0


def main() -> None:
    configure_logging()
    raise SystemExit(run_cli())
