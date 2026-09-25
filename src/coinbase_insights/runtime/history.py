from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from coinbase_insights.analytics.metrics import MidPriceObservation

DEFAULT_RETENTION = timedelta(minutes=15)
DEFAULT_MAX_ENTRIES = 181


class RollingWindow(StrEnum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"

    @property
    def duration(self) -> timedelta:
        match self:
            case RollingWindow.ONE_MINUTE:
                return timedelta(minutes=1)
            case RollingWindow.FIVE_MINUTES:
                return timedelta(minutes=5)
            case RollingWindow.FIFTEEN_MINUTES:
                return timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class RollingAverage:
    average: Decimal
    sample_count: int


class MidPriceHistory:
    def __init__(
        self,
        *,
        retention: timedelta = DEFAULT_RETENTION,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        if retention <= timedelta(0):
            raise ValueError("retention must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._retention = retention
        self._max_entries = max_entries
        self._observations: deque[MidPriceObservation] = deque()
        self._product_id: str | None = None

    def __len__(self) -> int:
        return len(self._observations)

    def append(self, observation: MidPriceObservation) -> None:
        if self._observations and observation.observed_at <= self._observations[-1].observed_at:
            raise ValueError("observation timestamps must be strictly increasing")
        if self._product_id is not None and observation.product_id != self._product_id:
            raise ValueError("history cannot mix products")
        self._product_id = observation.product_id
        self._observations.append(observation)
        self._prune(observation.observed_at)
        while len(self._observations) > self._max_entries:
            self._observations.popleft()

    def observations(self, *, at: datetime, window: timedelta) -> tuple[MidPriceObservation, ...]:
        self._validate_query(at=at, window=window)
        self._prune(at)
        lower_bound = at - window
        return tuple(
            observation
            for observation in self._observations
            if lower_bound < observation.observed_at <= at
        )

    def average(self, *, at: datetime, window: timedelta) -> RollingAverage | None:
        observations = self.observations(at=at, window=window)
        if not observations:
            return None
        total = sum(
            (observation.mid_price for observation in observations),
            start=Decimal(0),
        )
        return RollingAverage(
            average=total / Decimal(len(observations)),
            sample_count=len(observations),
        )

    def required_averages(self, *, at: datetime) -> dict[RollingWindow, RollingAverage | None]:
        return {window: self.average(at=at, window=window.duration) for window in RollingWindow}

    def _prune(self, at: datetime) -> None:
        cutoff = at - self._retention
        while self._observations and self._observations[0].observed_at <= cutoff:
            self._observations.popleft()

    def _validate_query(self, *, at: datetime, window: timedelta) -> None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must be timezone-aware")
        if window <= timedelta(0):
            raise ValueError("window must be positive")
        if window > self._retention:
            raise ValueError("window must not exceed retention")
