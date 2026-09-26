import argparse
import asyncio
import logging
import signal
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from coinbase_insights.coinbase.client import BackoffPolicy, CoinbaseFeedClient
from coinbase_insights.config import AppConfig, LogLevel, OutputMode
from coinbase_insights.output import render_console, write_ndjson
from coinbase_insights.runtime.sampler import (
    AsyncForecastService,
    FeedTerminalError,
    RuntimeSampler,
    run_runtime,
)

SUCCESS = 0
RUNTIME_ERROR = 1
CONFIGURATION_ERROR = 2
STARTUP_ERROR = 3

logger = logging.getLogger("coinbase_insights")


async def run_application(config: AppConfig) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_number, stop_event.set)
            installed_signals.append(signal_number)
        except NotImplementedError:
            pass

    jwt = None if config.jwt is None else config.jwt.get_secret_value()
    client = CoinbaseFeedClient(
        product_id=config.product_id,
        jwt=jwt,
        heartbeat_timeout_seconds=config.heartbeat_timeout_seconds,
        initial_snapshot_timeout_seconds=config.initial_snapshot_timeout_seconds,
        backoff=BackoffPolicy(cap_seconds=float(config.reconnect_cap_seconds)),
    )
    sampler = RuntimeSampler(
        product_id=config.product_id,
        forecast_service=AsyncForecastService(
            timeout_seconds=float(config.forecast_fit_timeout_seconds)
        ),
    )
    render = write_ndjson if config.output_mode is OutputMode.NDJSON else render_console
    try:
        await run_runtime(
            feed_events=client.events(),
            sampler=sampler,
            render=render,
            stop_event=stop_event,
        )
    finally:
        for signal_number in installed_signals:
            loop.remove_signal_handler(signal_number)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    arguments = parser.parse_args(argv)
    try:
        environment_config = AppConfig.from_environment(product_id=arguments.product)
        config_values = environment_config.model_dump()
        config_values.update(
            output_mode=arguments.output,
            log_level=arguments.log_level,
        )
        config = AppConfig.model_validate(config_values)
    except ValidationError as error:
        print(f"invalid configuration: {error}", file=sys.stderr)
        return CONFIGURATION_ERROR

    logging.basicConfig(
        level=config.log_level.value,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )
    try:
        asyncio.run(run_application(config))
    except FeedTerminalError as error:
        logger.error("startup failed: %s", error)
        return STARTUP_ERROR
    except KeyboardInterrupt:
        return SUCCESS
    except Exception as error:
        logger.error("runtime failed: %s", error)
        return RUNTIME_ERROR
    return SUCCESS


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coinbase-insights",
        description="Stream Coinbase Level 2 market insights.",
    )
    parser.add_argument("--product", default="BTC-USD", help="Coinbase product, e.g. BTC-USD")
    parser.add_argument(
        "--output",
        type=OutputMode,
        choices=tuple(OutputMode),
        default=OutputMode.CONSOLE,
        help="output format",
    )
    parser.add_argument(
        "--log-level",
        type=LogLevel,
        choices=tuple(LogLevel),
        default=LogLevel.INFO,
        help="diagnostic log level",
    )
    return parser
