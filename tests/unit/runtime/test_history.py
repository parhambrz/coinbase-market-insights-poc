from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from coinbase_insights.analytics.metrics import MidPriceObservation
from coinbase_insights.runtime.history import MidPriceHistory, RollingAverage, RollingWindow

PRODUCT_ID = "BTC-USD"
NOW = datetime(2026, 9, 26, 12, 15, tzinfo=UTC)


def observation(seconds_before_now: int, price: str) -> MidPriceObservation:
    return MidPriceObservation(
        product_id=PRODUCT_ID,
        observed_at=NOW - timedelta(seconds=seconds_before_now),
        mid_price=Decimal(price),
    )


def test_window_excludes_exact_lower_bound_and_includes_current_timestamp() -> None:
    history = MidPriceHistory()
    history.append(observation(60, "90"))
    history.append(observation(55, "100"))
    history.append(observation(0, "102"))

    result = history.average(at=NOW, window=timedelta(minutes=1))

    assert result == RollingAverage(average=Decimal("101"), sample_count=2)


def test_startup_partial_window_exposes_reduced_sample_count() -> None:
    history = MidPriceHistory()
    history.append(observation(10, "100"))
    history.append(observation(5, "101"))
    history.append(observation(0, "102"))

    result = history.average(at=NOW, window=timedelta(minutes=5))

    assert result == RollingAverage(average=Decimal("101"), sample_count=3)


def test_required_averages_return_one_five_and_fifteen_minute_windows() -> None:
    history = MidPriceHistory()
    history.append(observation(600, "90"))
    history.append(observation(240, "96"))
    history.append(observation(30, "100"))
    history.append(observation(0, "102"))

    results = history.required_averages(at=NOW)

    assert results == {
        RollingWindow.ONE_MINUTE: RollingAverage(Decimal("101"), 2),
        RollingWindow.FIVE_MINUTES: RollingAverage(Decimal("99.33333333333333333333333333"), 3),
        RollingWindow.FIFTEEN_MINUTES: RollingAverage(Decimal("97"), 4),
    }


def test_empty_window_is_unavailable_instead_of_zero() -> None:
    history = MidPriceHistory()

    assert history.average(at=NOW, window=timedelta(minutes=1)) is None


def test_old_entries_are_pruned_while_required_entries_remain() -> None:
    history = MidPriceHistory(retention=timedelta(minutes=15), max_entries=181)
    history.append(observation(901, "90"))
    history.append(observation(899, "100"))
    history.append(observation(0, "102"))

    assert len(history) == 2
    result = history.average(at=NOW, window=timedelta(minutes=15))
    assert result == RollingAverage(average=Decimal("101"), sample_count=2)


def test_memory_remains_bounded_after_long_regular_sequence() -> None:
    history = MidPriceHistory(retention=timedelta(minutes=15), max_entries=181)
    start = NOW - timedelta(hours=24)

    for index in range(17_281):
        history.append(
            MidPriceObservation(
                product_id=PRODUCT_ID,
                observed_at=start + timedelta(seconds=index * 5),
                mid_price=Decimal(index + 1),
            )
        )

    assert len(history) <= 181


def test_entry_cap_bounds_repeated_high_frequency_observations() -> None:
    history = MidPriceHistory(retention=timedelta(minutes=15), max_entries=3)

    for index in range(5):
        history.append(
            MidPriceObservation(
                product_id=PRODUCT_ID,
                observed_at=NOW + timedelta(microseconds=index),
                mid_price=Decimal(index + 1),
            )
        )

    assert len(history) == 3


def test_out_of_order_or_duplicate_observations_are_rejected() -> None:
    history = MidPriceHistory()
    history.append(observation(0, "100"))

    with pytest.raises(ValueError, match="strictly increasing"):
        history.append(observation(0, "101"))
    with pytest.raises(ValueError, match="strictly increasing"):
        history.append(observation(5, "99"))


def test_window_larger_than_retention_is_rejected() -> None:
    history = MidPriceHistory(retention=timedelta(minutes=15))

    with pytest.raises(ValueError, match="must not exceed retention"):
        history.average(at=NOW, window=timedelta(minutes=16))


def test_average_retains_decimal_precision() -> None:
    history = MidPriceHistory()
    history.append(observation(5, "100.000000000000000001"))
    history.append(observation(0, "100.000000000000000003"))

    result = history.average(at=NOW, window=timedelta(minutes=1))

    assert result == RollingAverage(
        average=Decimal("100.000000000000000002"),
        sample_count=2,
    )
