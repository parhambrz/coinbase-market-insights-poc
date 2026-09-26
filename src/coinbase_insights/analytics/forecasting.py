from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from statsmodels.tsa.ar_model import AutoReg

from coinbase_insights.analytics.metrics import MidPriceObservation
from coinbase_insights.runtime.history import RollingAverage, RollingWindow

SAMPLE_INTERVAL = timedelta(seconds=5)
FORECAST_HORIZON = timedelta(seconds=60)
MINIMUM_OBSERVATIONS = 60
MAXIMUM_OBSERVATIONS = 180
AUTOREG_LAGS = 12
FORECAST_STEPS = 12
ERROR_RETENTION = timedelta(minutes=15)


class ForecastRole(StrEnum):
    PRIMARY = "primary"
    NAIVE = "naive"


class ForecastModel(StrEnum):
    AUTOREG_DIFF_LAG12 = "autoreg_diff_lag12"
    NAIVE_PERSISTENCE = "naive_persistence"


class ForecastStatus(StrEnum):
    READY = "ready"
    FALLBACK_INSUFFICIENT_HISTORY = "fallback_insufficient_history"
    FALLBACK_GAPPED_HISTORY = "fallback_gapped_history"
    FALLBACK_MODEL_ERROR = "fallback_model_error"
    FALLBACK_TIMEOUT = "fallback_timeout"
    FALLBACK_NON_FINITE = "fallback_non_finite"


class ForecastScoreStatus(StrEnum):
    SCORED = "scored"
    UNSCORED_MISSING_TARGET = "unscored_missing_target"


@dataclass(frozen=True, slots=True)
class Forecast:
    product_id: str
    predicted_at: datetime
    target_at: datetime
    role: ForecastRole
    model: ForecastModel
    value: Decimal
    status: ForecastStatus


@dataclass(frozen=True, slots=True)
class ForecastBundle:
    primary: Forecast
    naive: Forecast

    def __post_init__(self) -> None:
        if self.primary.role is not ForecastRole.PRIMARY:
            raise ValueError("primary forecast must have the primary role")
        if self.naive.role is not ForecastRole.NAIVE:
            raise ValueError("naive forecast must have the naive role")
        primary_identity = (
            self.primary.product_id,
            self.primary.predicted_at,
            self.primary.target_at,
        )
        naive_identity = (
            self.naive.product_id,
            self.naive.predicted_at,
            self.naive.target_at,
        )
        if primary_identity != naive_identity:
            raise ValueError("primary and naive forecasts must share identity and target")


@dataclass(frozen=True, slots=True)
class ForecastScore:
    forecast: Forecast
    status: ForecastScoreStatus
    actual_value: Decimal | None
    absolute_error: Decimal | None


@dataclass(frozen=True, slots=True)
class _ErrorObservation:
    observed_at: datetime
    absolute_error: Decimal


class DifferenceForecaster(Protocol):
    def forecast_differences(
        self,
        differences: tuple[Decimal, ...],
        *,
        lags: int,
        steps: int,
    ) -> tuple[Decimal, ...]: ...


class StatsmodelsAutoRegForecaster:
    def forecast_differences(
        self,
        differences: tuple[Decimal, ...],
        *,
        lags: int,
        steps: int,
    ) -> tuple[Decimal, ...]:
        values: NDArray[np.float64] = np.asarray(differences, dtype=np.float64)
        fitted = AutoReg(values, lags=lags, old_names=False).fit()
        predictions: NDArray[np.float64] = np.asarray(
            fitted.predict(start=len(values), end=len(values) + steps - 1),
            dtype=np.float64,
        )
        return tuple(Decimal(str(value)) for value in predictions)


def create_forecast(
    observations: tuple[MidPriceObservation, ...],
    *,
    predicted_at: datetime,
    primary_forecaster: DifferenceForecaster | None = None,
) -> ForecastBundle:
    _require_aware(predicted_at, "predicted_at")
    eligible = tuple(
        observation for observation in observations if observation.observed_at <= predicted_at
    )
    if not eligible:
        raise ValueError("at least one valid observation is required")
    if eligible[-1].observed_at != predicted_at:
        raise ValueError("latest observation must be at predicted_at")
    product_id = eligible[-1].product_id
    if any(observation.product_id != product_id for observation in eligible):
        raise ValueError("forecast history cannot mix products")

    naive = _make_forecast(
        product_id=product_id,
        predicted_at=predicted_at,
        role=ForecastRole.NAIVE,
        model=ForecastModel.NAIVE_PERSISTENCE,
        value=eligible[-1].mid_price,
        status=ForecastStatus.READY,
    )
    training = eligible[-MAXIMUM_OBSERVATIONS:]
    if len(training) < MINIMUM_OBSERVATIONS:
        return _fallback_bundle(naive, ForecastStatus.FALLBACK_INSUFFICIENT_HISTORY)
    if not _is_contiguous(training):
        return _fallback_bundle(naive, ForecastStatus.FALLBACK_GAPPED_HISTORY)

    differences = tuple(
        current.mid_price - previous.mid_price for previous, current in pairwise(training)
    )
    forecaster = primary_forecaster or StatsmodelsAutoRegForecaster()
    try:
        predicted_differences = forecaster.forecast_differences(
            differences,
            lags=AUTOREG_LAGS,
            steps=FORECAST_STEPS,
        )
    except TimeoutError:
        return _fallback_bundle(naive, ForecastStatus.FALLBACK_TIMEOUT)
    except Exception:
        return _fallback_bundle(naive, ForecastStatus.FALLBACK_MODEL_ERROR)

    if len(predicted_differences) != FORECAST_STEPS or any(
        not value.is_finite() for value in predicted_differences
    ):
        return _fallback_bundle(naive, ForecastStatus.FALLBACK_NON_FINITE)
    forecast_value = naive.value + sum(predicted_differences, start=Decimal(0))
    if not forecast_value.is_finite() or forecast_value <= 0:
        return _fallback_bundle(naive, ForecastStatus.FALLBACK_NON_FINITE)
    primary = _make_forecast(
        product_id=product_id,
        predicted_at=predicted_at,
        role=ForecastRole.PRIMARY,
        model=ForecastModel.AUTOREG_DIFF_LAG12,
        value=forecast_value,
        status=ForecastStatus.READY,
    )
    return ForecastBundle(primary=primary, naive=naive)


class PredictionLedger:
    def __init__(
        self,
        *,
        max_pending: int = 25,
        max_errors_per_role: int = 181,
    ) -> None:
        if max_pending <= 0 or max_errors_per_role <= 0:
            raise ValueError("ledger bounds must be positive")
        self._max_pending = max_pending
        self._max_errors_per_role = max_errors_per_role
        self._pending: deque[ForecastBundle] = deque()
        self._errors: dict[ForecastRole, deque[_ErrorObservation]] = {
            ForecastRole.PRIMARY: deque(),
            ForecastRole.NAIVE: deque(),
        }

    def __len__(self) -> int:
        return len(self._pending)

    def append(self, prediction: ForecastBundle) -> None:
        if (
            self._pending
            and prediction.primary.predicted_at <= self._pending[-1].primary.predicted_at
        ):
            raise ValueError("prediction timestamps must be strictly increasing")
        self._pending.append(prediction)
        while len(self._pending) > self._max_pending:
            self._pending.popleft()

    def mature(self, observation: MidPriceObservation) -> tuple[ForecastScore, ...]:
        scores: list[ForecastScore] = []
        while self._pending and self._pending[0].primary.target_at <= observation.observed_at:
            prediction = self._pending.popleft()
            if prediction.primary.product_id != observation.product_id:
                raise ValueError("prediction and observation products must match")
            if prediction.primary.target_at == observation.observed_at:
                scores.extend(self._score(prediction, observation))
            else:
                scores.extend(self._unscored(prediction))
        return tuple(scores)

    def mature_missing(
        self,
        *,
        product_id: str,
        target_at: datetime,
    ) -> tuple[ForecastScore, ...]:
        _require_aware(target_at, "target_at")
        scores: list[ForecastScore] = []
        while self._pending and self._pending[0].primary.target_at <= target_at:
            prediction = self._pending.popleft()
            if prediction.primary.product_id != product_id:
                raise ValueError("prediction and missing target products must match")
            scores.extend(self._unscored(prediction))
        return tuple(scores)

    def error_count(self, role: ForecastRole) -> int:
        return len(self._errors[role])

    def mean_absolute_errors(
        self, *, at: datetime
    ) -> dict[ForecastRole, dict[RollingWindow, RollingAverage | None]]:
        _require_aware(at, "at")
        results: dict[ForecastRole, dict[RollingWindow, RollingAverage | None]] = {}
        for role, errors in self._errors.items():
            self._prune_errors(errors, at=at)
            results[role] = {
                window: self._mean_error(errors, at=at, window=window.duration)
                for window in RollingWindow
            }
        return results

    def _score(
        self,
        prediction: ForecastBundle,
        observation: MidPriceObservation,
    ) -> tuple[ForecastScore, ForecastScore]:
        primary = self._scored_forecast(prediction.primary, observation)
        naive = self._scored_forecast(prediction.naive, observation)
        return primary, naive

    def _scored_forecast(
        self,
        forecast: Forecast,
        observation: MidPriceObservation,
    ) -> ForecastScore:
        absolute_error = abs(forecast.value - observation.mid_price)
        errors = self._errors[forecast.role]
        errors.append(
            _ErrorObservation(
                observed_at=observation.observed_at,
                absolute_error=absolute_error,
            )
        )
        self._prune_errors(errors, at=observation.observed_at)
        while len(errors) > self._max_errors_per_role:
            errors.popleft()
        return ForecastScore(
            forecast=forecast,
            status=ForecastScoreStatus.SCORED,
            actual_value=observation.mid_price,
            absolute_error=absolute_error,
        )

    def _unscored(self, prediction: ForecastBundle) -> tuple[ForecastScore, ForecastScore]:
        primary = ForecastScore(
            forecast=prediction.primary,
            status=ForecastScoreStatus.UNSCORED_MISSING_TARGET,
            actual_value=None,
            absolute_error=None,
        )
        naive = ForecastScore(
            forecast=prediction.naive,
            status=ForecastScoreStatus.UNSCORED_MISSING_TARGET,
            actual_value=None,
            absolute_error=None,
        )
        return primary, naive

    def _prune_errors(self, errors: deque[_ErrorObservation], *, at: datetime) -> None:
        cutoff = at - ERROR_RETENTION
        while errors and errors[0].observed_at <= cutoff:
            errors.popleft()

    def _mean_error(
        self,
        errors: deque[_ErrorObservation],
        *,
        at: datetime,
        window: timedelta,
    ) -> RollingAverage | None:
        lower_bound = at - window
        included = tuple(error for error in errors if lower_bound < error.observed_at <= at)
        if not included:
            return None
        total = sum((error.absolute_error for error in included), start=Decimal(0))
        return RollingAverage(
            average=total / Decimal(len(included)),
            sample_count=len(included),
        )


def _make_forecast(
    *,
    product_id: str,
    predicted_at: datetime,
    role: ForecastRole,
    model: ForecastModel,
    value: Decimal,
    status: ForecastStatus,
) -> Forecast:
    return Forecast(
        product_id=product_id,
        predicted_at=predicted_at,
        target_at=predicted_at + FORECAST_HORIZON,
        role=role,
        model=model,
        value=value,
        status=status,
    )


def _fallback_bundle(naive: Forecast, status: ForecastStatus) -> ForecastBundle:
    primary = _make_forecast(
        product_id=naive.product_id,
        predicted_at=naive.predicted_at,
        role=ForecastRole.PRIMARY,
        model=ForecastModel.AUTOREG_DIFF_LAG12,
        value=naive.value,
        status=status,
    )
    return ForecastBundle(primary=primary, naive=naive)


def _is_contiguous(observations: tuple[MidPriceObservation, ...]) -> bool:
    return all(
        current.observed_at - previous.observed_at == SAMPLE_INTERVAL
        for previous, current in pairwise(observations)
    )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
