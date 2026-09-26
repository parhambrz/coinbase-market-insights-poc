import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from coinbase_insights.coinbase.mapper import (
    MappedHeartbeatEnvelope,
    MappedLevel2Envelope,
    MappedSubscriptionEnvelope,
    map_envelope,
)
from coinbase_insights.coinbase.messages import parse_envelope
from coinbase_insights.domain.events import BookSnapshot, PriceLevelUpdate, Side
from coinbase_insights.domain.order_book import OrderBook

FIXTURES = Path(__file__).parents[2] / "fixtures" / "coinbase"
RECEIVED_AT = datetime(2026, 9, 25, 12, 0, 1, tzinfo=UTC)


def test_snapshot_maps_decimal_levels_and_distinct_metadata() -> None:
    source = parse_envelope((FIXTURES / "level2_snapshot.json").read_text())

    mapped = map_envelope(source, received_at=RECEIVED_AT)

    assert isinstance(mapped, MappedLevel2Envelope)
    assert mapped.source_sequence == 100
    assert mapped.server_time == datetime(2026, 9, 25, 12, 0, 0, 500000, tzinfo=UTC)
    assert mapped.received_at == RECEIVED_AT
    assert len(mapped.events) == 1
    snapshot = mapped.events[0]
    assert isinstance(snapshot, BookSnapshot)
    assert snapshot.event_time == datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    assert snapshot.bids[0].price == Decimal("100.000000000000000001")
    assert snapshot.bids[0].quantity == Decimal("2.5")
    assert snapshot.asks[0].price == Decimal("101.000000000000000002")
    assert snapshot.asks[0].quantity == Decimal("3.5")


def test_updates_map_offer_to_ask_bid_to_bid_and_preserve_zero() -> None:
    source = parse_envelope((FIXTURES / "level2_updates.jsonl").read_text())

    mapped = map_envelope(source, received_at=RECEIVED_AT)

    assert isinstance(mapped, MappedLevel2Envelope)
    assert len(mapped.events) == 2
    bid, ask = mapped.events
    assert isinstance(bid, PriceLevelUpdate)
    assert bid.side is Side.BID
    assert bid.quantity == Decimal("4.25")
    assert isinstance(ask, PriceLevelUpdate)
    assert ask.side is Side.ASK
    assert ask.quantity == Decimal("0")


def test_heartbeat_maps_to_typed_health_signal() -> None:
    source = parse_envelope((FIXTURES / "heartbeat.json").read_text())

    mapped = map_envelope(source, received_at=RECEIVED_AT)

    assert isinstance(mapped, MappedHeartbeatEnvelope)
    assert mapped.source_sequence == 99
    assert mapped.server_time == datetime(2026, 9, 25, 12, 0, 0, 500000, tzinfo=UTC)
    assert mapped.received_at == RECEIVED_AT
    assert mapped.heartbeats[0].current_time == datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    assert mapped.heartbeats[0].counter == 42


def test_subscription_acknowledgement_maps_without_losing_sequence() -> None:
    source = parse_envelope((FIXTURES / "live_subscriptions_2026-09-26.json").read_text())

    mapped = map_envelope(source, received_at=RECEIVED_AT)

    assert isinstance(mapped, MappedSubscriptionEnvelope)
    assert mapped.source_sequence == 3
    assert mapped.subscriptions[0].channel == "level2"
    assert mapped.subscriptions[0].product_ids == ("BTC-USD",)


def test_naive_receive_time_is_rejected() -> None:
    source = parse_envelope((FIXTURES / "heartbeat.json").read_text())

    with pytest.raises(ValueError, match="received_at must be timezone-aware"):
        map_envelope(source, received_at=datetime(2026, 9, 25, 12, 0, 1))


def test_invalid_envelope_cannot_partially_mutate_existing_book() -> None:
    book = OrderBook("BTC-USD")
    snapshot_source = parse_envelope((FIXTURES / "level2_snapshot.json").read_text())
    snapshot_envelope = map_envelope(snapshot_source, received_at=RECEIVED_AT)
    assert isinstance(snapshot_envelope, MappedLevel2Envelope)
    snapshot = snapshot_envelope.events[0]
    assert isinstance(snapshot, BookSnapshot)
    book.apply_snapshot(snapshot)
    state_before_invalid_input = book.current()

    payload = cast(
        dict[str, Any],
        json.loads((FIXTURES / "level2_updates.jsonl").read_text()),
    )
    events = cast(list[dict[str, Any]], payload["events"])
    updates = cast(list[dict[str, Any]], events[0]["updates"])
    updates[1]["new_quantity"] = "-1"

    with pytest.raises(ValidationError):
        source = parse_envelope(json.dumps(payload))
        map_envelope(source, received_at=RECEIVED_AT)

    assert book.current() == state_before_invalid_input
