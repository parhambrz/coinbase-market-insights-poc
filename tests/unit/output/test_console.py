from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

from rich.console import Console

from coinbase_insights.output.console import render_console
from coinbase_insights.output.models import FeedStatus, InsightResult
from coinbase_insights.output.ndjson import write_ndjson


def test_console_renders_same_status_and_values_without_mutation() -> None:
    result = InsightResult.unavailable(
        product_id="BTC-USD",
        as_of=datetime(2026, 9, 26, 12, 0, tzinfo=UTC),
        feed_status=FeedStatus.FEED_STALE,
        reason="heartbeat_timeout",
    )
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=100)
    ndjson_stream = StringIO()
    before = repr(result)

    render_console(result, console=console)
    write_ndjson(result, stream=ndjson_stream)

    rendered = stream.getvalue()
    ndjson = ndjson_stream.getvalue()
    for expected in ("BTC-USD", "feed_stale", "heartbeat_timeout"):
        assert expected in rendered
        assert expected in ndjson
    assert repr(result) == before


def test_console_preserves_decimal_text() -> None:
    result = InsightResult.unavailable(
        product_id="BTC-USD",
        as_of=datetime(2026, 9, 26, 12, 0, tzinfo=UTC),
        feed_status=FeedStatus.WARMING_UP,
        reason="insufficient_forecast_history",
    )
    result = InsightResult(
        product_id=result.product_id,
        as_of=result.as_of,
        feed_status=result.feed_status,
        reason=result.reason,
        data_age_ms=5,
        highest_bid=None,
        lowest_ask=None,
        current_spread=Decimal("0.000000000000000001"),
        max_spread_since_start=Decimal("0.000000000000000001"),
        average_mid_price=result.average_mid_price,
        forecast_60s=None,
        primary_errors=result.primary_errors,
        naive_errors=result.naive_errors,
    )
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=100)

    render_console(result, console=console)

    assert "0.000000000000000001" in stream.getvalue()
