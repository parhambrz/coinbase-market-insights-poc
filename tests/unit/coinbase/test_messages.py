import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from coinbase_insights.coinbase.messages import (
    HeartbeatEnvelope,
    Level2Envelope,
    parse_envelope,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "coinbase"


def load_payload(name: str) -> dict[str, Any]:
    loaded: object = json.loads((FIXTURES / name).read_text())
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def test_known_snapshot_update_and_heartbeat_payloads_validate() -> None:
    snapshot = parse_envelope((FIXTURES / "level2_snapshot.json").read_text())
    update = parse_envelope((FIXTURES / "level2_updates.jsonl").read_text())
    heartbeat = parse_envelope((FIXTURES / "heartbeat.json").read_text())

    assert isinstance(snapshot, Level2Envelope)
    assert snapshot.events[0].type == "snapshot"
    assert isinstance(update, Level2Envelope)
    assert update.events[0].type == "update"
    assert isinstance(heartbeat, HeartbeatEnvelope)
    assert heartbeat.events[0].heartbeat_counter == 42


def test_numeric_source_fields_remain_strings_after_validation() -> None:
    envelope = parse_envelope((FIXTURES / "level2_snapshot.json").read_text())
    assert isinstance(envelope, Level2Envelope)

    update = envelope.events[0].updates[0]
    assert update.price_level == "100.000000000000000001"
    assert update.new_quantity == "2.5"
    assert isinstance(update.price_level, str)
    assert isinstance(update.new_quantity, str)


def test_unknown_fields_are_forward_compatible() -> None:
    payload = load_payload("heartbeat.json")
    payload["future_envelope_field"] = {"nested": True}
    events = payload["events"]
    assert isinstance(events, list)
    assert isinstance(events[0], dict)
    events[0]["future_event_field"] = "accepted"

    parsed = parse_envelope(json.dumps(payload))

    assert isinstance(parsed, HeartbeatEnvelope)


@pytest.mark.parametrize("missing_field", ["timestamp", "sequence_num", "events"])
def test_missing_required_envelope_fields_fail(missing_field: str) -> None:
    payload = load_payload("level2_snapshot.json")
    del payload[missing_field]

    with pytest.raises(ValidationError):
        parse_envelope(json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("side", "ask"),
        ("event_time", "not-a-timestamp"),
        ("price_level", "0"),
        ("price_level", "not-a-number"),
        ("price_level", "NaN"),
        ("new_quantity", "-1"),
    ],
)
def test_invalid_level2_semantics_fail(field: str, invalid_value: object) -> None:
    payload = load_payload("level2_snapshot.json")
    events = payload["events"]
    assert isinstance(events, list)
    assert isinstance(events[0], dict)
    event = cast(dict[str, Any], events[0])
    updates = event["updates"]
    assert isinstance(updates, list)
    assert isinstance(updates[0], dict)
    update = cast(dict[str, Any], updates[0])
    update[field] = invalid_value

    with pytest.raises(ValidationError):
        parse_envelope(json.dumps(payload))


def test_invalid_envelope_timestamp_fails() -> None:
    payload = load_payload("heartbeat.json")
    payload["timestamp"] = "not-a-timestamp"

    with pytest.raises(ValidationError):
        parse_envelope(json.dumps(payload))


@pytest.mark.parametrize("invalid_quantity", ["0", "-1"])
def test_snapshot_requires_positive_quantities(invalid_quantity: str) -> None:
    payload = load_payload("level2_snapshot.json")
    events = cast(list[dict[str, Any]], payload["events"])
    updates = cast(list[dict[str, Any]], events[0]["updates"])
    updates[0]["new_quantity"] = invalid_quantity

    with pytest.raises(ValidationError):
        parse_envelope(json.dumps(payload))


def test_snapshot_requires_one_engine_timestamp() -> None:
    payload = load_payload("level2_snapshot.json")
    events = cast(list[dict[str, Any]], payload["events"])
    updates = cast(list[dict[str, Any]], events[0]["updates"])
    updates[1]["event_time"] = "2026-09-25T12:00:01Z"

    with pytest.raises(ValidationError):
        parse_envelope(json.dumps(payload))


def test_empty_event_and_update_collections_fail() -> None:
    payload = load_payload("level2_snapshot.json")
    payload["events"] = []
    with pytest.raises(ValidationError):
        parse_envelope(json.dumps(payload))

    payload = load_payload("level2_snapshot.json")
    events = payload["events"]
    assert isinstance(events, list)
    assert isinstance(events[0], dict)
    events[0]["updates"] = []
    with pytest.raises(ValidationError):
        parse_envelope(json.dumps(payload))
