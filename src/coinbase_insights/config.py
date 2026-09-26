import os
import re
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

PRODUCT_PATTERN = re.compile(r"^[A-Z0-9]+-[A-Z0-9]+$")


class OutputMode(StrEnum):
    CONSOLE = "console"
    NDJSON = "ndjson"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str = "BTC-USD"
    output_mode: OutputMode = OutputMode.CONSOLE
    jwt: SecretStr | None = Field(default=None, repr=False)
    log_level: LogLevel = LogLevel.INFO
    sample_interval_seconds: int = Field(default=5, gt=0)
    forecast_horizon_seconds: int = Field(default=60, gt=0)
    heartbeat_timeout_seconds: int = Field(default=15, gt=0)
    initial_snapshot_timeout_seconds: int = Field(default=30, gt=0)
    reconnect_cap_seconds: int = Field(default=30, gt=0)
    forecast_fit_timeout_seconds: int = Field(default=2, gt=0)
    forecast_history_size: int = Field(default=180, gt=0)
    forecast_min_observations: int = Field(default=60, gt=0)
    forecast_lags: int = Field(default=12, gt=0)
    forecast_steps: int = Field(default=12, gt=0)

    @field_validator("product_id", mode="before")
    @classmethod
    def normalize_product_id(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, value: str) -> str:
        if PRODUCT_PATTERN.fullmatch(value) is None:
            raise ValueError("product_id must look like BASE-QUOTE")
        return value

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> "AppConfig":
        if self.sample_interval_seconds != 5:
            raise ValueError("sample interval is fixed at five seconds")
        if self.forecast_horizon_seconds != 60:
            raise ValueError("forecast horizon is fixed at sixty seconds")
        if self.forecast_horizon_seconds % self.sample_interval_seconds != 0:
            raise ValueError("forecast horizon must be divisible by sample interval")
        if self.forecast_steps != self.forecast_horizon_seconds // self.sample_interval_seconds:
            raise ValueError("forecast steps must span the forecast horizon")
        if self.forecast_min_observations > self.forecast_history_size:
            raise ValueError("minimum observations must not exceed history size")
        if self.forecast_lags >= self.forecast_min_observations:
            raise ValueError("forecast lags must be below minimum observations")
        return self

    @classmethod
    def from_environment(
        cls,
        *,
        product_id: str = "BTC-USD",
        environ: Mapping[str, str] | None = None,
    ) -> "AppConfig":
        source = os.environ if environ is None else environ
        jwt_value = source.get("COINBASE_JWT") or None
        jwt = None if jwt_value is None else SecretStr(jwt_value)
        return cls(product_id=product_id, jwt=jwt)
