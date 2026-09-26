import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import TextIO

from coinbase_insights.output.models import (
    ForecastOutput,
    InsightResult,
    PriceLevelOutput,
    WindowMetric,
    WindowMetrics,
)


def result_to_dict(result: InsightResult) -> dict[str, object]:
    return {
        "product_id": result.product_id,
        "as_of": _timestamp(result.as_of),
        "feed_status": result.feed_status.value,
        "reason": result.reason,
        "data_age_ms": result.data_age_ms,
        "highest_bid": _price_level(result.highest_bid),
        "lowest_ask": _price_level(result.lowest_ask),
        "current_spread": _decimal(result.current_spread),
        "max_spread_since_start": _decimal(result.max_spread_since_start),
        "average_mid_price": _window_metrics(result.average_mid_price),
        "forecast_60s": _forecast(result.forecast_60s),
        "average_absolute_error": {
            "primary_1m": _window_metric(result.primary_errors.one_minute),
            "primary_5m": _window_metric(result.primary_errors.five_minutes),
            "primary_15m": _window_metric(result.primary_errors.fifteen_minutes),
            "naive_1m": _window_metric(result.naive_errors.one_minute),
            "naive_5m": _window_metric(result.naive_errors.five_minutes),
            "naive_15m": _window_metric(result.naive_errors.fifteen_minutes),
        },
    }


def write_ndjson(result: InsightResult, *, stream: TextIO | None = None) -> None:
    output = sys.stdout if stream is None else stream
    output.write(json.dumps(result_to_dict(result), separators=(",", ":"), ensure_ascii=True))
    output.write("\n")
    output.flush()


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _price_level(value: PriceLevelOutput | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {"price": format(value.price, "f"), "quantity": format(value.quantity, "f")}


def _window_metric(value: WindowMetric) -> dict[str, str | int | None]:
    return {"value": _decimal(value.value), "samples": value.samples}


def _window_metrics(value: WindowMetrics) -> dict[str, dict[str, str | int | None]]:
    return {
        "1m": _window_metric(value.one_minute),
        "5m": _window_metric(value.five_minutes),
        "15m": _window_metric(value.fifteen_minutes),
    }


def _forecast(value: ForecastOutput | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        "target_at": _timestamp(value.target_at),
        "model": value.model,
        "value": format(value.value, "f"),
        "naive_value": format(value.naive_value, "f"),
        "status": value.status.value,
    }
