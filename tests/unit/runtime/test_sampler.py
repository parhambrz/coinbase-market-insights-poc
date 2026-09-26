import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from coinbase_insights.analytics.forecasting import ForecastStatus
from coinbase_insights.coinbase.client import FeedEvent, FeedState
from coinbase_insights.coinbase.mapper import MappedLevel2Envelope
from coinbase_insights.domain.events import BookLevel, BookSnapshot, PriceLevelUpdate, Side
from coinbase_insights.output.models import FeedStatus, InsightResult
from coinbase_insights.runtime.sampler import (
    AsyncForecastService,
    RuntimeSampler,
    next_utc_boundary,
    run_runtime,
    run_sampling,
)

START = datetime(2026, 9, 26, 12, 0, 1, 750_000, tzinfo=UTC)


class FailingForecaster:
    def __init__(self) -> None:
        self.calls = 0

    def forecast_differences(
        self,
        differences: tuple[Decimal, ...],
        *,
        lags: int,
        steps: int,
    ) -> tuple[Decimal, ...]:
        del differences, lags, steps
        self.calls += 1
        raise RuntimeError("model failed")


def snapshot_event(
    *,
    bid: str = "100",
    ask: str = "102",
    received_at: datetime = START,
) -> FeedEvent:
    snapshot = BookSnapshot(
        product_id="BTC-USD",
        bids=(BookLevel(price=Decimal(bid), quantity=Decimal("2")),),
        asks=(BookLevel(price=Decimal(ask), quantity=Decimal("3")),),
        event_time=received_at,
    )
    return FeedEvent(
        connection_id="connection-1",
        state=FeedState.HEALTHY,
        envelope=MappedLevel2Envelope(
            source_sequence=1,
            server_time=received_at,
            received_at=received_at,
            events=(snapshot,),
        ),
    )


def update_event(
    *,
    side: Side,
    price: str,
    quantity: str,
    received_at: datetime,
) -> FeedEvent:
    update = PriceLevelUpdate(
        product_id="BTC-USD",
        side=side,
        price=Decimal(price),
        quantity=Decimal(quantity),
        event_time=received_at,
    )
    return FeedEvent(
        connection_id="connection-1",
        state=FeedState.HEALTHY,
        envelope=MappedLevel2Envelope(
            source_sequence=2,
            server_time=received_at,
            received_at=received_at,
            events=(update,),
        ),
    )


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (START, datetime(2026, 9, 26, 12, 0, 5, tzinfo=UTC)),
        (
            datetime(2026, 9, 26, 12, 0, 5, tzinfo=UTC),
            datetime(2026, 9, 26, 12, 0, 10, tzinfo=UTC),
        ),
        (
            datetime(2026, 9, 26, 12, 0, 58, tzinfo=UTC),
            datetime(2026, 9, 26, 12, 1, 0, tzinfo=UTC),
        ),
    ],
)
def test_next_boundary_is_utc_aligned_without_drift(
    current: datetime,
    expected: datetime,
) -> None:
    assert next_utc_boundary(current) == expected


@pytest.mark.asyncio
async def test_valid_snapshot_builds_one_complete_warming_up_result() -> None:
    sampler = RuntimeSampler(product_id="BTC-USD")
    sampler.consume(snapshot_event())

    result = await sampler.sample_at(datetime(2026, 9, 26, 12, 0, 5, tzinfo=UTC))

    assert result.feed_status is FeedStatus.WARMING_UP
    assert result.reason == "fallback_insufficient_history"
    assert result.data_age_ms == 3250
    assert result.highest_bid is not None
    assert result.highest_bid.price == Decimal("100")
    assert result.highest_bid.quantity == Decimal("2")
    assert result.lowest_ask is not None
    assert result.lowest_ask.price == Decimal("102")
    assert result.current_spread == Decimal("2")
    assert result.max_spread_since_start == Decimal("2")
    assert result.average_mid_price.one_minute.value == Decimal("101")
    assert result.average_mid_price.one_minute.samples == 1
    assert result.forecast_60s is not None
    assert result.forecast_60s.value == Decimal("101")
    assert result.forecast_60s.naive_value == Decimal("101")


@pytest.mark.asyncio
async def test_transient_spread_is_retained_between_sample_boundaries() -> None:
    sampler = RuntimeSampler(product_id="BTC-USD")
    sampler.consume(snapshot_event())
    sampler.consume(
        update_event(
            side=Side.ASK,
            price="102",
            quantity="0",
            received_at=START + timedelta(seconds=1),
        )
    )
    sampler.consume(
        update_event(
            side=Side.ASK,
            price="110",
            quantity="1",
            received_at=START + timedelta(seconds=2),
        )
    )
    sampler.consume(
        update_event(
            side=Side.ASK,
            price="101",
            quantity="4",
            received_at=START + timedelta(seconds=3),
        )
    )

    result = await sampler.sample_at(datetime(2026, 9, 26, 12, 0, 5, tzinfo=UTC))

    assert result.current_spread == Decimal("1")
    assert result.max_spread_since_start == Decimal("10")


@pytest.mark.asyncio
async def test_feed_invalidation_suppresses_all_numeric_output_immediately() -> None:
    sampler = RuntimeSampler(product_id="BTC-USD")
    sampler.consume(snapshot_event())
    sampler.consume(
        FeedEvent(
            connection_id="connection-1",
            state=FeedState.INVALIDATED,
            reason="sequence_gap",
            invalidates_book=True,
        )
    )

    result = await sampler.sample_at(datetime(2026, 9, 26, 12, 0, 5, tzinfo=UTC))

    assert result.feed_status is FeedStatus.FEED_STALE
    assert result.reason == "sequence_gap"
    assert result.highest_bid is None
    assert result.lowest_ask is None
    assert result.current_spread is None
    assert result.max_spread_since_start is None
    assert result.forecast_60s is None


@pytest.mark.asyncio
async def test_sampling_loop_recalculates_exact_boundaries_and_renders_once() -> None:
    sampler = RuntimeSampler(product_id="BTC-USD")
    sampler.consume(snapshot_event())
    current = START
    rendered_at: list[datetime] = []
    requested_delays: list[float] = []

    def utc_now() -> datetime:
        return current

    async def advance(delay: float) -> None:
        nonlocal current
        requested_delays.append(delay)
        current += timedelta(seconds=delay)

    def render(result: InsightResult) -> None:
        nonlocal current
        rendered_at.append(result.as_of)
        current += timedelta(milliseconds=700)

    await run_sampling(
        sampler,
        render=render,
        utc_now=utc_now,
        sleep=advance,
        sample_limit=3,
    )

    assert rendered_at == [
        datetime(2026, 9, 26, 12, 0, 5, tzinfo=UTC),
        datetime(2026, 9, 26, 12, 0, 10, tzinfo=UTC),
        datetime(2026, 9, 26, 12, 0, 15, tzinfo=UTC),
    ]
    assert requested_delays == [3.25, 4.3, 4.3]


@pytest.mark.asyncio
async def test_runtime_coordinates_feed_sampling_and_clean_shutdown() -> None:
    sampler = RuntimeSampler(product_id="BTC-USD")
    stop_event = asyncio.Event()
    rendered: list[InsightResult] = []
    feed_closed = False
    current = START

    async def feed() -> AsyncGenerator[FeedEvent]:
        nonlocal feed_closed
        try:
            yield snapshot_event()
            await asyncio.Event().wait()
        finally:
            feed_closed = True

    async def advance(delay: float) -> None:
        nonlocal current
        current += timedelta(seconds=delay)
        await asyncio.sleep(0)

    def render(result: InsightResult) -> None:
        rendered.append(result)
        stop_event.set()

    await run_runtime(
        feed_events=feed(),
        sampler=sampler,
        render=render,
        stop_event=stop_event,
        utc_now=lambda: current,
        sleep=advance,
    )

    assert len(rendered) == 1
    assert rendered[0].as_of == datetime(2026, 9, 26, 12, 0, 5, tzinfo=UTC)
    assert feed_closed


@pytest.mark.asyncio
async def test_forecast_matures_at_exact_sixty_second_target() -> None:
    sampler = RuntimeSampler(product_id="BTC-USD")
    first_boundary = datetime(2026, 9, 26, 12, 0, 5, tzinfo=UTC)
    result: InsightResult | None = None
    for index in range(13):
        boundary = first_boundary + timedelta(seconds=index * 5)
        ask = "104" if index == 12 else "102"
        sampler.consume(snapshot_event(ask=ask, received_at=boundary))
        result = await sampler.sample_at(boundary)

    assert result is not None
    assert result.primary_errors.one_minute.value == Decimal("1")
    assert result.primary_errors.one_minute.samples == 1
    assert result.naive_errors.one_minute.value == Decimal("1")
    assert result.naive_errors.one_minute.samples == 1
    assert result.average_mid_price.one_minute.samples == 12
    assert result.average_mid_price.five_minutes.samples == 13
    assert result.average_mid_price.fifteen_minutes.samples == 13


@pytest.mark.asyncio
async def test_model_failure_emits_fallback_and_sampling_continues() -> None:
    forecaster = FailingForecaster()
    sampler = RuntimeSampler(
        product_id="BTC-USD",
        forecast_service=AsyncForecastService(primary_forecaster=forecaster),
    )
    first_boundary = datetime(2026, 9, 26, 12, 0, 5, tzinfo=UTC)
    results: list[InsightResult] = []
    for index in range(61):
        boundary = first_boundary + timedelta(seconds=index * 5)
        sampler.consume(snapshot_event(received_at=boundary))
        results.append(await sampler.sample_at(boundary))

    assert forecaster.calls == 2
    assert [result.feed_status for result in results[-2:]] == [
        FeedStatus.FALLBACK,
        FeedStatus.FALLBACK,
    ]
    assert all(
        result.forecast_60s is not None
        and result.forecast_60s.status is ForecastStatus.FALLBACK_MODEL_ERROR
        for result in results[-2:]
    )
