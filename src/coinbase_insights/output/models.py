from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from coinbase_insights.analytics.forecasting import ForecastStatus


class FeedStatus(StrEnum):
    CONNECTING = "connecting"
    AWAITING_SNAPSHOT = "awaiting_snapshot"
    HEALTHY = "healthy"
    FEED_STALE = "feed_stale"
    WARMING_UP = "warming_up"
    FALLBACK = "fallback"


@dataclass(frozen=True, slots=True)
class PriceLevelOutput:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class WindowMetric:
    value: Decimal | None
    samples: int

    def __post_init__(self) -> None:
        if self.samples < 0:
            raise ValueError("samples must not be negative")
        if self.value is None and self.samples != 0:
            raise ValueError("an unavailable metric must have zero samples")
        if self.value is not None and self.samples == 0:
            raise ValueError("an available metric must have samples")


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    one_minute: WindowMetric
    five_minutes: WindowMetric
    fifteen_minutes: WindowMetric

    @classmethod
    def unavailable(cls) -> "WindowMetrics":
        unavailable = WindowMetric(value=None, samples=0)
        return cls(
            one_minute=unavailable,
            five_minutes=unavailable,
            fifteen_minutes=unavailable,
        )


@dataclass(frozen=True, slots=True)
class ForecastOutput:
    target_at: datetime
    model: str
    value: Decimal
    naive_value: Decimal
    status: ForecastStatus

    def __post_init__(self) -> None:
        _require_aware(self.target_at, "target_at")


@dataclass(frozen=True, slots=True)
class InsightResult:
    product_id: str
    as_of: datetime
    feed_status: FeedStatus
    reason: str | None
    data_age_ms: int | None
    highest_bid: PriceLevelOutput | None
    lowest_ask: PriceLevelOutput | None
    current_spread: Decimal | None
    max_spread_since_start: Decimal | None
    average_mid_price: WindowMetrics
    forecast_60s: ForecastOutput | None
    primary_errors: WindowMetrics
    naive_errors: WindowMetrics

    def __post_init__(self) -> None:
        if not self.product_id:
            raise ValueError("product_id must not be empty")
        _require_aware(self.as_of, "as_of")
        if self.data_age_ms is not None and self.data_age_ms < 0:
            raise ValueError("data_age_ms must not be negative")

    @classmethod
    def unavailable(
        cls,
        *,
        product_id: str,
        as_of: datetime,
        feed_status: FeedStatus,
        reason: str,
    ) -> "InsightResult":
        unavailable_windows = WindowMetrics.unavailable()
        return cls(
            product_id=product_id,
            as_of=as_of,
            feed_status=feed_status,
            reason=reason,
            data_age_ms=None,
            highest_bid=None,
            lowest_ask=None,
            current_spread=None,
            max_spread_since_start=None,
            average_mid_price=unavailable_windows,
            forecast_60s=None,
            primary_errors=unavailable_windows,
            naive_errors=unavailable_windows,
        )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
