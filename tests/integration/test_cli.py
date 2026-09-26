import pytest

from coinbase_insights.config import AppConfig, LogLevel, OutputMode
from coinbase_insights.runtime.sampler import FeedTerminalError


def test_cli_validates_and_normalizes_options_before_running(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from coinbase_insights import cli

    received: list[AppConfig] = []

    async def fake_run(config: AppConfig) -> None:
        received.append(config)

    monkeypatch.setattr(cli, "run_application", fake_run)

    exit_code = cli.main(["--product", " eth-usd ", "--output", "ndjson", "--log-level", "WARNING"])

    assert exit_code == 0
    assert len(received) == 1
    assert received[0].product_id == "ETH-USD"
    assert received[0].output_mode is OutputMode.NDJSON
    assert received[0].log_level is LogLevel.WARNING
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_invalid_configuration_fails_before_application_start(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from coinbase_insights import cli

    started = False

    async def fake_run(config: AppConfig) -> None:
        nonlocal started
        del config
        started = True

    monkeypatch.setattr(cli, "run_application", fake_run)

    exit_code = cli.main(["--product", "not-a-product"])

    assert exit_code == 2
    assert not started
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid configuration" in captured.err


@pytest.mark.parametrize(
    ("failure", "expected_code", "message"),
    [
        (FeedTerminalError("initial_snapshot_timeout"), 3, "startup failed"),
        (RuntimeError("unexpected"), 1, "runtime failed"),
    ],
)
def test_runtime_failures_have_meaningful_exit_codes_and_stay_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
    expected_code: int,
    message: str,
) -> None:
    from coinbase_insights import cli

    async def fail(config: AppConfig) -> None:
        del config
        raise failure

    monkeypatch.setattr(cli, "run_application", fail)

    assert cli.main([]) == expected_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err
