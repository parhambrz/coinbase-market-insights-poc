from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from coinbase_insights.analytics.forecasting import (
    Forecast,
    ForecastBundle,
    ForecastModel,
    ForecastRole,
    ForecastScoreStatus,
    ForecastStatus,
    PredictionLedger,
    create_forecast,
)
from coinbase_insights.analytics.metrics import MidPriceObservation
from coinbase_insights.runtime.history import RollingAverage, RollingWindow

PRODUCT_ID = "BTC-USD"
PREDICTED_AT = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def observations(
    count: int,
    *,
    end_at: datetime = PREDICTED_AT,
    gap_before_last: bool = False,
) -> tuple[MidPriceObservation, ...]:
    values: list[MidPriceObservation] = []
    start = end_at - timedelta(seconds=(count - 1) * 5)
    for index in range(count):
        observed_at = start + timedelta(seconds=index * 5)
        if gap_before_last and index == count - 1:
            observed_at += timedelta(seconds=5)
        trend = Decimal(index) / Decimal("10")
        curve = Decimal(index * index) / Decimal("10000")
        values.append(
            MidPriceObservation(
                product_id=PRODUCT_ID,
                observed_at=observed_at,
                mid_price=Decimal("100") + trend + curve,
            )
        )
    return tuple(values)


class RecordingForecaster:
    def __init__(
        self,
        *,
        result: tuple[Decimal, ...] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or (Decimal("0.1"),) * 12
        self.error = error
        self.received_differences: tuple[Decimal, ...] | None = None

    def forecast_differences(
        self,
        differences: tuple[Decimal, ...],
        *,
        lags: int,
        steps: int,
    ) -> tuple[Decimal, ...]:
        self.received_differences = differences
        assert lags == 12
        assert steps == 12
        if self.error is not None:
            raise self.error
        return self.result


def forecast(
    *,
    role: ForecastRole,
    value: str,
    predicted_at: datetime = PREDICTED_AT,
) -> Forecast:
    model = (
        ForecastModel.AUTOREG_DIFF_LAG12
        if role is ForecastRole.PRIMARY
        else ForecastModel.NAIVE_PERSISTENCE
    )
    return Forecast(
        product_id=PRODUCT_ID,
        predicted_at=predicted_at,
        target_at=predicted_at + timedelta(seconds=60),
        role=role,
        model=model,
        value=Decimal(value),
        status=ForecastStatus.READY,
    )


def bundle(
    *,
    primary: str,
    naive: str,
    predicted_at: datetime = PREDICTED_AT,
) -> ForecastBundle:
    return ForecastBundle(
        primary=forecast(
            role=ForecastRole.PRIMARY,
            value=primary,
            predicted_at=predicted_at,
        ),
        naive=forecast(
            role=ForecastRole.NAIVE,
            value=naive,
            predicted_at=predicted_at,
        ),
    )


def test_naive_forecast_uses_latest_value_and_exact_sixty_second_target() -> None:
    history = observations(1)

    result = create_forecast(history, predicted_at=PREDICTED_AT)

    assert result.naive.value == history[-1].mid_price
    assert result.naive.predicted_at == PREDICTED_AT
    assert result.naive.target_at == PREDICTED_AT + timedelta(seconds=60)
    assert result.naive.model is ForecastModel.NAIVE_PERSISTENCE
    assert result.naive.status is ForecastStatus.READY


def test_primary_forecast_uses_naive_fallback_during_warmup() -> None:
    history = observations(59)

    result = create_forecast(history, predicted_at=PREDICTED_AT)

    assert result.primary.value == result.naive.value
    assert result.primary.status is ForecastStatus.FALLBACK_INSUFFICIENT_HISTORY


def test_deterministic_synthetic_trend_produces_finite_autoreg_forecast() -> None:
    result = create_forecast(observations(180), predicted_at=PREDICTED_AT)

    assert result.primary.status is ForecastStatus.READY
    assert result.primary.model is ForecastModel.AUTOREG_DIFF_LAG12
    assert result.primary.value.is_finite()
    assert result.primary.value > 0


def test_training_uses_only_latest_180_observations_at_or_before_cutoff() -> None:
    model = RecordingForecaster()
    eligible = observations(200)
    future = MidPriceObservation(
        product_id=PRODUCT_ID,
        observed_at=PREDICTED_AT + timedelta(seconds=5),
        mid_price=Decimal("999999"),
    )

    result = create_forecast(
        (*eligible, future),
        predicted_at=PREDICTED_AT,
        primary_forecaster=model,
    )

    assert result.primary.status is ForecastStatus.READY
    assert model.received_differences is not None
    assert len(model.received_differences) == 179
    assert max(model.received_differences) < Decimal("1")


def test_gap_in_training_history_selects_naive_fallback() -> None:
    history = observations(60, end_at=PREDICTED_AT - timedelta(seconds=5), gap_before_last=True)

    result = create_forecast(history, predicted_at=PREDICTED_AT)

    assert result.primary.value == result.naive.value
    assert result.primary.status is ForecastStatus.FALLBACK_GAPPED_HISTORY


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (RuntimeError("fit failed"), ForecastStatus.FALLBACK_MODEL_ERROR),
        (np.linalg.LinAlgError("singular"), ForecastStatus.FALLBACK_MODEL_ERROR),
        (TimeoutError("fit timed out"), ForecastStatus.FALLBACK_TIMEOUT),
    ],
)
def test_primary_model_exceptions_select_naive_fallback(
    error: Exception,
    expected_status: ForecastStatus,
) -> None:
    result = create_forecast(
        observations(60),
        predicted_at=PREDICTED_AT,
        primary_forecaster=RecordingForecaster(error=error),
    )

    assert result.primary.value == result.naive.value
    assert result.primary.status is expected_status


@pytest.mark.parametrize(
    "result",
    [
        (Decimal("NaN"),) * 12,
        (Decimal("Infinity"),) * 12,
        (Decimal("-1000"),) * 12,
        (Decimal("0.1"),) * 11,
    ],
)
def test_invalid_primary_output_selects_naive_fallback(
    result: tuple[Decimal, ...],
) -> None:
    forecast_result = create_forecast(
        observations(60),
        predicted_at=PREDICTED_AT,
        primary_forecaster=RecordingForecaster(result=result),
    )

    assert forecast_result.primary.value == forecast_result.naive.value
    assert forecast_result.primary.status is ForecastStatus.FALLBACK_NON_FINITE


def test_exact_target_matures_primary_and_naive_once() -> None:
    ledger = PredictionLedger()
    ledger.append(bundle(primary="110", naive="100"))
    actual = MidPriceObservation(
        product_id=PRODUCT_ID,
        observed_at=PREDICTED_AT + timedelta(seconds=60),
        mid_price=Decimal("102"),
    )

    scores = ledger.mature(actual)

    assert [score.absolute_error for score in scores] == [Decimal("8"), Decimal("2")]
    assert all(score.status is ForecastScoreStatus.SCORED for score in scores)
    assert ledger.mature(actual) == ()


def test_missing_target_is_unscored_and_never_shifted_to_later_sample() -> None:
    ledger = PredictionLedger()
    ledger.append(bundle(primary="110", naive="100"))
    late_observation = MidPriceObservation(
        product_id=PRODUCT_ID,
        observed_at=PREDICTED_AT + timedelta(seconds=65),
        mid_price=Decimal("102"),
    )

    scores = ledger.mature(late_observation)

    assert len(scores) == 2
    assert all(score.status is ForecastScoreStatus.UNSCORED_MISSING_TARGET for score in scores)
    assert all(score.absolute_error is None for score in scores)
    assert ledger.error_count(ForecastRole.PRIMARY) == 0
    assert ledger.error_count(ForecastRole.NAIVE) == 0


def test_primary_and_naive_rolling_errors_remain_separate() -> None:
    ledger = PredictionLedger()
    ledger.append(bundle(primary="110", naive="100"))
    target_at = PREDICTED_AT + timedelta(seconds=60)
    ledger.mature(
        MidPriceObservation(
            product_id=PRODUCT_ID,
            observed_at=target_at,
            mid_price=Decimal("102"),
        )
    )

    errors = ledger.mean_absolute_errors(at=target_at)

    assert errors[ForecastRole.PRIMARY][RollingWindow.ONE_MINUTE] == RollingAverage(Decimal("8"), 1)
    assert errors[ForecastRole.NAIVE][RollingWindow.ONE_MINUTE] == RollingAverage(Decimal("2"), 1)


def test_prediction_and_error_histories_are_bounded() -> None:
    ledger = PredictionLedger(max_pending=3, max_errors_per_role=2)

    for index in range(5):
        predicted_at = PREDICTED_AT + timedelta(seconds=index * 5)
        ledger.append(bundle(primary="110", naive="100", predicted_at=predicted_at))

    assert len(ledger) == 3

    for index in range(3):
        predicted_at = PREDICTED_AT + timedelta(minutes=index + 10)
        ledger.append(bundle(primary="110", naive="100", predicted_at=predicted_at))
        ledger.mature(
            MidPriceObservation(
                product_id=PRODUCT_ID,
                observed_at=predicted_at + timedelta(seconds=60),
                mid_price=Decimal("102"),
            )
        )

    assert ledger.error_count(ForecastRole.PRIMARY) == 2
    assert ledger.error_count(ForecastRole.NAIVE) == 2
