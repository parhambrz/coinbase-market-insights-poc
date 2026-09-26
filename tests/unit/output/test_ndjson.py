import json
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from typing import Any, cast

import pytest

from coinbase_insights.analytics.forecasting import ForecastStatus
from coinbase_insights.output.models import (
    FeedStatus,
    ForecastOutput,
    InsightResult,
    PriceLevelOutput,
    WindowMetric,
    WindowMetrics,
)
from coinbase_insights.output.ndjson import result_to_dict, write_ndjson

AS_OF = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def windows(one: str, five: str, fifteen: str) -> WindowMetrics:
    return WindowMetrics(
        one_minute=WindowMetric(Decimal(one), 12),
        five_minutes=WindowMetric(Decimal(five), 60),
        fifteen_minutes=WindowMetric(Decimal(fifteen), 180),
    )


def healthy_result() -> InsightResult:
    return InsightResult(
        product_id="BTC-USD",
        as_of=AS_OF,
        feed_status=FeedStatus.HEALTHY,
        reason=None,
        data_age_ms=42,
        highest_bid=PriceLevelOutput(Decimal("109999.10"), Decimal("0.42")),
        lowest_ask=PriceLevelOutput(Decimal("110000.20"), Decimal("0.31")),
        current_spread=Decimal("1.10"),
        max_spread_since_start=Decimal("3.40"),
        average_mid_price=windows("109998.45", "109990.12", "109970.80"),
        forecast_60s=ForecastOutput(
            target_at=AS_OF.replace(minute=1),
            model="autoreg_diff_lag12",
            value=Decimal("110005.30"),
            naive_value=Decimal("109999.65"),
            status=ForecastStatus.READY,
        ),
        primary_errors=windows("8.21", "7.94", "8.12"),
        naive_errors=windows("7.90", "8.02", "8.20"),
    )


def test_ndjson_schema_uses_decimal_strings_utc_timestamps_and_one_line() -> None:
    stream = StringIO()

    write_ndjson(healthy_result(), stream=stream)

    rendered = stream.getvalue()
    assert rendered.count("\n") == 1
    assert rendered.endswith("\n")
    payload = cast(dict[str, Any], json.loads(rendered))
    assert payload["as_of"] == "2026-09-26T12:00:00Z"
    assert payload["highest_bid"] == {"price": "109999.10", "quantity": "0.42"}
    assert payload["current_spread"] == "1.10"
    assert payload["average_mid_price"]["1m"] == {
        "value": "109998.45",
        "samples": 12,
    }
    assert payload["forecast_60s"]["target_at"] == "2026-09-26T12:01:00Z"
    assert payload["forecast_60s"]["value"] == "110005.30"
    assert payload["average_absolute_error"]["naive_15m"]["value"] == "8.20"


def test_unavailable_status_has_null_values_and_explicit_reason() -> None:
    result = InsightResult.unavailable(
        product_id="BTC-USD",
        as_of=AS_OF,
        feed_status=FeedStatus.AWAITING_SNAPSHOT,
        reason="awaiting_snapshot",
    )

    payload = result_to_dict(result)

    assert payload["feed_status"] == "awaiting_snapshot"
    assert payload["reason"] == "awaiting_snapshot"
    assert payload["highest_bid"] is None
    assert payload["current_spread"] is None
    average_mid_price = cast(dict[str, object], payload["average_mid_price"])
    assert average_mid_price["15m"] == {"value": None, "samples": 0}
    assert payload["forecast_60s"] is None


def test_fallback_forecast_status_is_preserved() -> None:
    result = healthy_result()
    assert result.forecast_60s is not None
    fallback = ForecastOutput(
        target_at=result.forecast_60s.target_at,
        model=result.forecast_60s.model,
        value=result.forecast_60s.naive_value,
        naive_value=result.forecast_60s.naive_value,
        status=ForecastStatus.FALLBACK_MODEL_ERROR,
    )
    fallback_result = InsightResult(
        product_id=result.product_id,
        as_of=result.as_of,
        feed_status=FeedStatus.FALLBACK,
        reason="forecast_model_error",
        data_age_ms=result.data_age_ms,
        highest_bid=result.highest_bid,
        lowest_ask=result.lowest_ask,
        current_spread=result.current_spread,
        max_spread_since_start=result.max_spread_since_start,
        average_mid_price=result.average_mid_price,
        forecast_60s=fallback,
        primary_errors=result.primary_errors,
        naive_errors=result.naive_errors,
    )

    payload = result_to_dict(fallback_result)

    assert payload["feed_status"] == "fallback"
    rendered_forecast = cast(dict[str, object], payload["forecast_60s"])
    assert rendered_forecast["status"] == "fallback_model_error"


def test_rendering_does_not_mutate_result() -> None:
    result = healthy_result()

    before = repr(result)
    result_to_dict(result)

    assert repr(result) == before


def test_default_ndjson_stream_contains_only_record_and_no_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_ndjson(healthy_result())

    captured = capsys.readouterr()
    payload: object = json.loads(captured.out)
    assert isinstance(payload, dict)
    assert payload["product_id"] == "BTC-USD"
    assert captured.out.count("\n") == 1
    assert captured.err == ""
