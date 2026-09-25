from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from coinbase_insights.domain.models import BestBidAsk, BookState


def _require_decimal(value: object, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")


@dataclass(frozen=True, slots=True)
class CurrentMarketMetrics:
    spread: Decimal
    mid_price: Decimal


@dataclass(frozen=True, slots=True)
class MidPriceObservation:
    product_id: str
    observed_at: datetime
    mid_price: Decimal

    def __post_init__(self) -> None:
        if not self.product_id:
            raise ValueError("product_id must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        _require_decimal(self.mid_price, "mid_price")
        if not self.mid_price.is_finite() or self.mid_price <= 0:
            raise ValueError("mid_price must be finite and positive")


class MaximumSpreadTracker:
    def __init__(self) -> None:
        self._maximum: Decimal | None = None

    @property
    def maximum(self) -> Decimal | None:
        return self._maximum

    def observe(self, book: BookState) -> Decimal | None:
        metrics = calculate_current_metrics(book)
        if metrics is not None and (self._maximum is None or metrics.spread > self._maximum):
            self._maximum = metrics.spread
        return self._maximum


def calculate_current_metrics(book: BookState) -> CurrentMarketMetrics | None:
    if not isinstance(book, BestBidAsk):
        return None
    if (
        book.bid_price <= 0
        or book.ask_price <= 0
        or book.bid_quantity <= 0
        or book.ask_quantity <= 0
        or book.bid_price > book.ask_price
    ):
        return None
    return CurrentMarketMetrics(
        spread=book.ask_price - book.bid_price,
        mid_price=(book.ask_price + book.bid_price) / Decimal(2),
    )


def observe_mid_price(book: BookState, *, observed_at: datetime) -> MidPriceObservation | None:
    metrics = calculate_current_metrics(book)
    if metrics is None:
        return None
    return MidPriceObservation(
        product_id=book.product_id,
        observed_at=observed_at,
        mid_price=metrics.mid_price,
    )
