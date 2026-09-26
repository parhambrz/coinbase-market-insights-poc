import pytest
from pydantic import ValidationError

from coinbase_insights.config import AppConfig, LogLevel, OutputMode


def test_product_is_normalized_and_defaults_are_production_values() -> None:
    config = AppConfig(product_id=" btc-usd ")

    assert config.product_id == "BTC-USD"
    assert config.output_mode is OutputMode.CONSOLE
    assert config.log_level is LogLevel.INFO
    assert config.sample_interval_seconds == 5
    assert config.forecast_horizon_seconds == 60
    assert config.forecast_history_size == 180
    assert config.forecast_min_observations == 60
    assert config.forecast_lags == 12
    assert config.forecast_steps == 12


@pytest.mark.parametrize(
    "product_id",
    ["", "BTCUSD", "BTC/USD", "BTC--USD", "btc usd", "BTC-USD!"],
)
def test_invalid_product_is_rejected(product_id: str) -> None:
    with pytest.raises(ValidationError):
        AppConfig(product_id=product_id)


def test_optional_jwt_is_loaded_but_never_appears_in_representation() -> None:
    secret = "sensitive-jwt-value"

    config = AppConfig.from_environment(
        product_id="BTC-USD",
        environ={"COINBASE_JWT": secret},
    )

    assert config.jwt is not None
    assert config.jwt.get_secret_value() == secret
    assert secret not in repr(config)
    assert secret not in str(config)
    assert secret not in config.model_dump_json()


def test_public_feed_configuration_does_not_require_jwt() -> None:
    config = AppConfig.from_environment(product_id="BTC-USD", environ={})

    assert config.jwt is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_interval_seconds", 0),
        ("forecast_horizon_seconds", 55),
        ("heartbeat_timeout_seconds", 0),
        ("initial_snapshot_timeout_seconds", 0),
        ("reconnect_cap_seconds", 0),
        ("forecast_fit_timeout_seconds", 0),
        ("forecast_history_size", 59),
        ("forecast_min_observations", 181),
        ("forecast_lags", 60),
        ("forecast_steps", 11),
    ],
)
def test_incompatible_runtime_settings_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"product_id": "BTC-USD", field: value})
