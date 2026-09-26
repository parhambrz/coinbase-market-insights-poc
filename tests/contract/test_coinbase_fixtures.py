from datetime import UTC, datetime
from pathlib import Path

from coinbase_insights.coinbase.mapper import (
    MappedHeartbeatEnvelope,
    MappedLevel2Envelope,
    MappedSubscriptionEnvelope,
    map_envelope,
)
from coinbase_insights.coinbase.messages import parse_envelope

FIXTURES = Path(__file__).parents[1] / "fixtures" / "coinbase"
RECEIVED_AT = datetime(2026, 9, 25, 12, 0, 1, tzinfo=UTC)


def fixture_messages() -> list[str]:
    messages = [
        (FIXTURES / "heartbeat.json").read_text(),
        (FIXTURES / "level2_snapshot.json").read_text(),
    ]
    messages.extend((FIXTURES / "level2_updates.jsonl").read_text().splitlines())
    messages.extend(
        (FIXTURES / name).read_text()
        for name in (
            "live_subscriptions_2026-09-26.json",
            "live_heartbeat_2026-09-26.json",
            "live_level2_snapshot_2026-09-26.json",
            "live_level2_update_2026-09-26.json",
        )
    )
    return messages


def test_every_synthetic_fixture_validates_and_maps_to_typed_output() -> None:
    mapped = [
        map_envelope(parse_envelope(message), received_at=RECEIVED_AT)
        for message in fixture_messages()
    ]

    assert all(
        isinstance(
            item,
            MappedHeartbeatEnvelope | MappedLevel2Envelope | MappedSubscriptionEnvelope,
        )
        for item in mapped
    )
