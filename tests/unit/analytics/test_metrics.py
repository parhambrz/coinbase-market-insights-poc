from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from coinbase_insights.analytics.metrics import (
    MaximumSpreadTracker,
    MidPriceObservation,
    calculate_current_metrics,
    observe_mid_price,
)
from coinbase_insights.domain.models import (
    BestBidAsk,
    BookUnavailable,
    BookUnavailableReason,
)

PRODUCT_ID = "BTC-USD"
EVENT_TIME = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def bbo(bid: str, ask: str, *, event_time: datetime = EVENT_TIME) -> BestBidAsk:
    return BestBidAsk(
        product_id=PRODUCT_ID,
        bid_price=Decimal(bid),
        bid_quantity=Decimal("1.25"),
        ask_price=Decimal(ask),
        ask_quantity=Decimal("2.5"),
        event_time=event_time,
    )


def unavailable() -> BookUnavailable:
    return BookUnavailable(
        product_id=PRODUCT_ID,
        reason=BookUnavailableReason.INVALIDATED,
        event_time=EVENT_TIME,
    )


def test_current_spread_and_mid_price_retain_decimal_precision() -> None:
    current = calculate_current_metrics(bbo("100.000000000000000001", "101.000000000000000003"))

    assert current is not None
    assert current.spread == Decimal("1.000000000000000002")
    assert current.mid_price == Decimal("100.500000000000000002")


def test_invalid_or_crossed_book_has_no_numeric_metrics() -> None:
    assert calculate_current_metrics(unavailable()) is None
    assert calculate_current_metrics(bbo("102", "101")) is None


def test_mid_price_observation_is_immutable_and_uses_observation_time() -> None:
    observed_at = EVENT_TIME + timedelta(seconds=2)

    observation = observe_mid_price(bbo("100", "102"), observed_at=observed_at)

    assert observation == MidPriceObservation(
        product_id=PRODUCT_ID,
        observed_at=observed_at,
        mid_price=Decimal("101"),
    )
    assert observation is not None
    field_name = "mid_price"
    with pytest.raises(FrozenInstanceError):
        setattr(observation, field_name, Decimal("0"))


def test_invalid_book_does_not_produce_mid_price_observation() -> None:
    assert observe_mid_price(unavailable(), observed_at=EVENT_TIME) is None


def test_maximum_spread_tracks_transient_bbo_changes_between_samples() -> None:
    tracker = MaximumSpreadTracker()

    assert tracker.observe(bbo("100", "101")) == Decimal("1")
    assert tracker.observe(bbo("98", "103")) == Decimal("5")
    assert tracker.observe(bbo("100", "102")) == Decimal("5")
    assert tracker.maximum == Decimal("5")


def test_invalid_book_does_not_change_maximum_spread() -> None:
    tracker = MaximumSpreadTracker()
    tracker.observe(bbo("100", "101"))

    assert tracker.observe(unavailable()) == Decimal("1")
    assert tracker.maximum == Decimal("1")


def test_maximum_spread_is_unavailable_before_first_valid_bbo() -> None:
    tracker = MaximumSpreadTracker()

    assert tracker.maximum is None
    assert tracker.observe(unavailable()) is None
