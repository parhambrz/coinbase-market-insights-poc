import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from coinbase_insights.analytics.forecasting import (
    DifferenceForecaster,
    ForecastBundle,
    ForecastRole,
    ForecastStatus,
    PredictionLedger,
    create_forecast,
)
from coinbase_insights.analytics.metrics import (
    MaximumSpreadTracker,
    MidPriceObservation,
    calculate_current_metrics,
    observe_mid_price,
)
from coinbase_insights.coinbase.client import FeedEvent, FeedState
from coinbase_insights.coinbase.mapper import MappedLevel2Envelope
from coinbase_insights.domain.events import BookSnapshot
from coinbase_insights.domain.models import BestBidAsk
from coinbase_insights.domain.order_book import OrderBook
from coinbase_insights.output.models import (
    FeedStatus,
    ForecastOutput,
    InsightResult,
    PriceLevelOutput,
    WindowMetric,
    WindowMetrics,
)
from coinbase_insights.runtime.history import MidPriceHistory, RollingAverage, RollingWindow

DEFAULT_SAMPLE_INTERVAL_SECONDS = 5
DEFAULT_FORECAST_FIT_TIMEOUT_SECONDS = 2.0
FORECAST_HISTORY = timedelta(minutes=15)

type Renderer = Callable[[InsightResult], None]


class FeedTerminalError(RuntimeError):
    pass


class ForecastService(Protocol):
    async def create(
        self,
        observations: tuple[MidPriceObservation, ...],
        *,
        predicted_at: datetime,
    ) -> ForecastBundle: ...


class AsyncForecastService:
    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_FORECAST_FIT_TIMEOUT_SECONDS,
        primary_forecaster: DifferenceForecaster | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds
        self._primary_forecaster = primary_forecaster

    async def create(
        self,
        observations: tuple[MidPriceObservation, ...],
        *,
        predicted_at: datetime,
    ) -> ForecastBundle:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    create_forecast,
                    observations,
                    predicted_at=predicted_at,
                    primary_forecaster=self._primary_forecaster,
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            return create_forecast(
                observations,
                predicted_at=predicted_at,
                primary_forecaster=_TimeoutForecaster(),
            )


class _TimeoutForecaster:
    def forecast_differences(
        self,
        differences: tuple[Decimal, ...],
        *,
        lags: int,
        steps: int,
    ) -> tuple[Decimal, ...]:
        del differences, lags, steps
        raise TimeoutError


class RuntimeSampler:
    def __init__(
        self,
        *,
        product_id: str,
        forecast_service: ForecastService | None = None,
    ) -> None:
        self._product_id = product_id
        self._book = OrderBook(product_id)
        self._maximum_spread = MaximumSpreadTracker()
        self._history = MidPriceHistory()
        self._ledger = PredictionLedger()
        self._forecast_service = forecast_service or AsyncForecastService()
        self._feed_state = FeedState.CONNECTING
        self._feed_reason: str | None = None
        self._last_book_received_at: datetime | None = None

    def consume(self, feed_event: FeedEvent) -> None:
        self._feed_state = feed_event.state
        self._feed_reason = feed_event.reason
        if feed_event.invalidates_book:
            self._book.invalidate()
            self._last_book_received_at = None
        if not isinstance(feed_event.envelope, MappedLevel2Envelope):
            return
        for event in feed_event.envelope.events:
            if isinstance(event, BookSnapshot):
                self._book.apply_snapshot(event)
            else:
                self._book.apply_update(event)
            self._maximum_spread.observe(self._book.current())
        self._last_book_received_at = feed_event.envelope.received_at

    async def sample_at(self, sampled_at: datetime) -> InsightResult:
        _require_aware(sampled_at)
        book = self._book.current()
        observation = observe_mid_price(book, observed_at=sampled_at)
        if observation is None or not isinstance(book, BestBidAsk):
            self._ledger.mature_missing(product_id=self._product_id, target_at=sampled_at)
            return InsightResult.unavailable(
                product_id=self._product_id,
                as_of=sampled_at,
                feed_status=_unavailable_feed_status(self._feed_state),
                reason=self._feed_reason or "invalid_book",
            )

        self._ledger.mature(observation)
        self._history.append(observation)
        averages = self._history.required_averages(at=sampled_at)
        errors = self._ledger.mean_absolute_errors(at=sampled_at)
        forecast = await self._forecast_service.create(
            self._history.observations(at=sampled_at, window=FORECAST_HISTORY),
            predicted_at=sampled_at,
        )
        self._ledger.append(forecast)
        metrics = calculate_current_metrics(book)
        if metrics is None:
            raise RuntimeError("valid BBO did not produce market metrics")
        status, reason = _forecast_feed_status(forecast)
        return InsightResult(
            product_id=self._product_id,
            as_of=sampled_at,
            feed_status=status,
            reason=reason,
            data_age_ms=_data_age_ms(sampled_at, self._last_book_received_at),
            highest_bid=PriceLevelOutput(price=book.bid_price, quantity=book.bid_quantity),
            lowest_ask=PriceLevelOutput(price=book.ask_price, quantity=book.ask_quantity),
            current_spread=metrics.spread,
            max_spread_since_start=self._maximum_spread.maximum,
            average_mid_price=_window_metrics(averages),
            forecast_60s=ForecastOutput(
                target_at=forecast.primary.target_at,
                model=forecast.primary.model.value,
                value=forecast.primary.value,
                naive_value=forecast.naive.value,
                status=forecast.primary.status,
            ),
            primary_errors=_window_metrics(errors[ForecastRole.PRIMARY]),
            naive_errors=_window_metrics(errors[ForecastRole.NAIVE]),
        )


async def run_sampling(
    sampler: RuntimeSampler,
    *,
    render: Renderer,
    utc_now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    stop_event: asyncio.Event | None = None,
    sample_limit: int | None = None,
) -> None:
    if sample_limit is not None and sample_limit <= 0:
        raise ValueError("sample_limit must be positive")
    current_time = utc_now or _utc_now
    wait = sleep or asyncio.sleep
    samples = 0
    while (sample_limit is None or samples < sample_limit) and not (
        stop_event is not None and stop_event.is_set()
    ):
        now = current_time()
        boundary = next_utc_boundary(now)
        delay = max(0.0, (boundary - now).total_seconds())
        await wait(delay)
        if stop_event is not None and stop_event.is_set():
            return
        render(await sampler.sample_at(boundary))
        samples += 1


async def run_runtime(
    *,
    feed_events: AsyncIterator[FeedEvent],
    sampler: RuntimeSampler,
    render: Renderer,
    stop_event: asyncio.Event,
    utc_now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> None:
    reader_task = asyncio.create_task(_consume_feed(feed_events, sampler))
    sampler_task = asyncio.create_task(
        run_sampling(
            sampler,
            render=render,
            utc_now=utc_now,
            sleep=sleep,
            stop_event=stop_event,
        )
    )
    stop_task = asyncio.create_task(stop_event.wait())
    tasks = (reader_task, sampler_task, stop_task)
    try:
        completed, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if stop_task not in completed:
            for task in completed:
                task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _consume_feed(
    feed_events: AsyncIterator[FeedEvent],
    sampler: RuntimeSampler,
) -> None:
    async for feed_event in feed_events:
        sampler.consume(feed_event)
        if feed_event.state is FeedState.TERMINAL:
            raise FeedTerminalError(feed_event.reason or "feed_startup_failed")
    raise FeedTerminalError("feed_ended")


def next_utc_boundary(
    current: datetime,
    *,
    interval_seconds: int = DEFAULT_SAMPLE_INTERVAL_SECONDS,
) -> datetime:
    _require_aware(current)
    if interval_seconds <= 0 or 60 % interval_seconds != 0:
        raise ValueError("interval_seconds must be a positive divisor of 60")
    seconds_to_boundary = interval_seconds - (current.second % interval_seconds)
    return current.replace(microsecond=0) + timedelta(seconds=seconds_to_boundary)


def _window_metrics(
    values: dict[RollingWindow, RollingAverage | None],
) -> WindowMetrics:
    return WindowMetrics(
        one_minute=_window_metric(values[RollingWindow.ONE_MINUTE]),
        five_minutes=_window_metric(values[RollingWindow.FIVE_MINUTES]),
        fifteen_minutes=_window_metric(values[RollingWindow.FIFTEEN_MINUTES]),
    )


def _window_metric(value: RollingAverage | None) -> WindowMetric:
    if value is None:
        return WindowMetric(value=None, samples=0)
    return WindowMetric(value=value.average, samples=value.sample_count)


def _forecast_feed_status(forecast: ForecastBundle) -> tuple[FeedStatus, str | None]:
    status = forecast.primary.status
    if status is ForecastStatus.READY:
        return FeedStatus.HEALTHY, None
    if status is ForecastStatus.FALLBACK_INSUFFICIENT_HISTORY:
        return FeedStatus.WARMING_UP, status.value
    return FeedStatus.FALLBACK, status.value


def _unavailable_feed_status(feed_state: FeedState) -> FeedStatus:
    if feed_state is FeedState.CONNECTING:
        return FeedStatus.CONNECTING
    if feed_state is FeedState.AWAITING_SNAPSHOT:
        return FeedStatus.AWAITING_SNAPSHOT
    return FeedStatus.FEED_STALE


def _data_age_ms(sampled_at: datetime, received_at: datetime | None) -> int | None:
    if received_at is None:
        return None
    return max(0, int((sampled_at - received_at).total_seconds() * 1000))


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")


def _utc_now() -> datetime:
    return datetime.now(UTC)
