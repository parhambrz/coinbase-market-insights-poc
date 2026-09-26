import json
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import pytest

from coinbase_insights.coinbase.client import (
    COINBASE_WEBSOCKET_URL,
    MAX_MESSAGE_SIZE_BYTES,
    WEBSOCKET_CLOSE_TIMEOUT_SECONDS,
    BackoffPolicy,
    CoinbaseFeedClient,
    FeedEvent,
    FeedState,
    WebsocketsTransportFactory,
    build_subscription_messages,
)
from coinbase_insights.coinbase.mapper import (
    MappedHeartbeatEnvelope,
    MappedLevel2Envelope,
    MappedSubscriptionEnvelope,
    map_envelope,
)
from coinbase_insights.coinbase.messages import parse_envelope
from coinbase_insights.domain.events import BookSnapshot, PriceLevelUpdate
from coinbase_insights.domain.models import BestBidAsk, BookUnavailable
from coinbase_insights.domain.order_book import OrderBook

FIXTURES = Path(__file__).parents[2] / "fixtures" / "coinbase"
RECEIVED_AT = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def payload(name: str) -> str:
    return (FIXTURES / name).read_text()


def with_sequence(raw_message: str, sequence: int) -> str:
    parsed = cast(dict[str, object], json.loads(raw_message))
    parsed["sequence_num"] = sequence
    return json.dumps(parsed)


class ScriptedTransport:
    def __init__(self, script: list[str | bytes | BaseException]) -> None:
        self._script = iter(script)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def receive(self, *, timeout_seconds: float) -> str | bytes:
        del timeout_seconds
        item = next(self._script)
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


class ScriptedFactory:
    def __init__(self, transports: list[ScriptedTransport]) -> None:
        self._transports = iter(transports)
        self.calls = 0

    async def __call__(self) -> ScriptedTransport:
        self.calls += 1
        return next(self._transports)


class ScriptedClock:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


async def collect_until(
    events: AsyncGenerator[FeedEvent],
    predicate: Callable[[FeedEvent], bool],
) -> list[FeedEvent]:
    collected: list[FeedEvent] = []
    async for event in events:
        collected.append(event)
        if predicate(event):
            await events.aclose()
            return collected
    return collected


def test_subscription_messages_without_optional_jwt_are_exact() -> None:
    level2, heartbeats = build_subscription_messages(product_id="BTC-USD", jwt=None)

    assert json.loads(level2) == {
        "type": "subscribe",
        "channel": "level2",
        "product_ids": ["BTC-USD"],
    }
    assert json.loads(heartbeats) == {
        "type": "subscribe",
        "channel": "heartbeats",
    }


def test_subscription_messages_include_optional_jwt_without_other_changes() -> None:
    level2, heartbeats = build_subscription_messages(product_id="BTC-USD", jwt="secret")

    assert json.loads(level2)["jwt"] == "secret"
    assert json.loads(heartbeats)["jwt"] == "secret"


@pytest.mark.asyncio
async def test_live_transport_allows_bounded_multi_megabyte_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from coinbase_insights.coinbase import client as client_module

    connection = object()
    connect_mock = AsyncMock(return_value=connection)
    monkeypatch.setattr(client_module, "connect", connect_mock)

    await WebsocketsTransportFactory()()

    connect_mock.assert_awaited_once_with(
        COINBASE_WEBSOCKET_URL,
        ping_interval=None,
        max_size=MAX_MESSAGE_SIZE_BYTES,
        close_timeout=WEBSOCKET_CLOSE_TIMEOUT_SECONDS,
    )


@pytest.mark.asyncio
async def test_contiguous_level2_and_heartbeat_stream_maps_complete_envelopes() -> None:
    transport = ScriptedTransport(
        [
            with_sequence(payload("level2_snapshot.json"), 100),
            with_sequence(payload("live_subscriptions_2026-09-26.json"), 101),
            with_sequence(payload("heartbeat.json"), 102),
            with_sequence(payload("level2_updates.jsonl"), 103),
            ConnectionError("closed"),
        ]
    )
    client = CoinbaseFeedClient(
        product_id="BTC-USD",
        transport_factory=ScriptedFactory([transport]),
        utc_now=lambda: RECEIVED_AT,
        connection_id_factory=lambda: "connection-1",
        sleep=_no_sleep,
    )

    events = await collect_until(
        client.events(),
        lambda event: event.state is FeedState.INVALIDATED,
    )

    assert [event.state for event in events] == [
        FeedState.CONNECTING,
        FeedState.AWAITING_SNAPSHOT,
        FeedState.HEALTHY,
        FeedState.HEALTHY,
        FeedState.HEALTHY,
        FeedState.HEALTHY,
        FeedState.INVALIDATED,
    ]
    assert all(event.connection_id == "connection-1" for event in events)
    snapshot = events[2].envelope
    subscription = events[3].envelope
    heartbeat = events[4].envelope
    update = events[5].envelope
    assert isinstance(snapshot, MappedLevel2Envelope)
    assert isinstance(snapshot.events[0], BookSnapshot)
    assert isinstance(subscription, MappedSubscriptionEnvelope)
    assert isinstance(heartbeat, MappedHeartbeatEnvelope)
    assert isinstance(update, MappedLevel2Envelope)
    assert all(isinstance(item, PriceLevelUpdate) for item in update.events)
    assert transport.sent == list(build_subscription_messages(product_id="BTC-USD", jwt=None))
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("second_sequence", "reason"),
    [(102, "sequence_gap"), (100, "sequence_regression")],
)
async def test_gap_and_regression_invalidate_before_reconnect(
    second_sequence: int,
    reason: str,
) -> None:
    first = ScriptedTransport(
        [
            with_sequence(payload("level2_snapshot.json"), 100),
            with_sequence(payload("heartbeat.json"), second_sequence),
        ]
    )
    second = ScriptedTransport([with_sequence(payload("level2_snapshot.json"), 200)])
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = CoinbaseFeedClient(
        product_id="BTC-USD",
        transport_factory=ScriptedFactory([first, second]),
        utc_now=lambda: RECEIVED_AT,
        connection_id_factory=iter(["one", "two"]).__next__,
        sleep=record_sleep,
        jitter=lambda: 0.5,
    )

    events = await collect_until(
        client.events(),
        lambda event: event.connection_id == "two" and event.state is FeedState.HEALTHY,
    )

    failure_index = next(index for index, event in enumerate(events) if event.reason == reason)
    assert events[failure_index].state is FeedState.INVALIDATED
    assert events[failure_index].invalidates_book
    assert events[failure_index + 1].state is FeedState.RECONNECTING
    assert events[failure_index + 2].state is FeedState.CONNECTING
    assert events[failure_index + 3].state is FeedState.AWAITING_SNAPSHOT
    assert events[failure_index + 4].state is FeedState.HEALTHY
    assert sleeps == [1.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (ConnectionError("closed"), "disconnected"),
        (TimeoutError("stale"), "heartbeat_timeout"),
        ("not-json", "malformed_message"),
    ],
)
async def test_transport_and_parse_failures_emit_invalidation_before_reconnect(
    failure: str | BaseException,
    reason: str,
) -> None:
    transport = ScriptedTransport([failure])
    client = CoinbaseFeedClient(
        product_id="BTC-USD",
        transport_factory=ScriptedFactory([transport]),
        utc_now=lambda: RECEIVED_AT,
        connection_id_factory=lambda: "connection-1",
        sleep=_no_sleep,
    )

    events = await collect_until(
        client.events(),
        lambda event: event.state is FeedState.RECONNECTING,
    )

    assert events[-2].state is FeedState.INVALIDATED
    assert events[-2].reason == reason
    assert events[-2].invalidates_book
    assert events[-1].state is FeedState.RECONNECTING


@pytest.mark.asyncio
async def test_update_before_fresh_snapshot_is_rejected_on_new_connection() -> None:
    transport = ScriptedTransport([with_sequence(payload("level2_updates.jsonl"), 1)])
    client = CoinbaseFeedClient(
        product_id="BTC-USD",
        transport_factory=ScriptedFactory([transport]),
        utc_now=lambda: RECEIVED_AT,
        connection_id_factory=lambda: "connection-1",
        sleep=_no_sleep,
    )

    events = await collect_until(
        client.events(),
        lambda event: event.state is FeedState.INVALIDATED,
    )

    assert events[-1].reason == "update_before_snapshot"
    assert events[-1].envelope is None


@pytest.mark.asyncio
async def test_level2_traffic_cannot_mask_stale_heartbeat() -> None:
    transport = ScriptedTransport(
        [
            with_sequence(payload("level2_snapshot.json"), 1),
            with_sequence(payload("level2_updates.jsonl"), 2),
        ]
    )
    client = CoinbaseFeedClient(
        product_id="BTC-USD",
        transport_factory=ScriptedFactory([transport]),
        utc_now=lambda: RECEIVED_AT,
        monotonic=ScriptedClock([0.0, 1.0, 16.0]),
        connection_id_factory=lambda: "connection-1",
        sleep=_no_sleep,
        heartbeat_timeout_seconds=15.0,
    )

    events = await collect_until(
        client.events(),
        lambda event: event.state is FeedState.INVALIDATED,
    )

    assert events[-1].reason == "heartbeat_timeout"
    assert events[-1].invalidates_book


@pytest.mark.asyncio
async def test_new_connection_invalidates_old_book_and_fresh_snapshot_restores_it() -> None:
    book = OrderBook("BTC-USD")
    mapped_snapshot = cast(
        MappedLevel2Envelope,
        map_envelope(
            parse_envelope(with_sequence(payload("level2_snapshot.json"), 1)),
            received_at=RECEIVED_AT,
        ),
    )
    initial_snapshot = mapped_snapshot.events[0]
    assert isinstance(initial_snapshot, BookSnapshot)
    book.apply_snapshot(initial_snapshot)
    assert isinstance(book.current(), BestBidAsk)

    transport = ScriptedTransport([with_sequence(payload("level2_snapshot.json"), 10)])
    client = CoinbaseFeedClient(
        product_id="BTC-USD",
        transport_factory=ScriptedFactory([transport]),
        utc_now=lambda: RECEIVED_AT,
        connection_id_factory=lambda: "replacement",
        sleep=_no_sleep,
    )
    was_invalidated = False
    event_stream = client.events()
    async for event in event_stream:
        if event.invalidates_book:
            book.invalidate()
            was_invalidated = isinstance(book.current(), BookUnavailable)
        if event.state is FeedState.HEALTHY:
            assert isinstance(event.envelope, MappedLevel2Envelope)
            snapshot = event.envelope.events[0]
            assert isinstance(snapshot, BookSnapshot)
            book.apply_snapshot(snapshot)
            break
    await event_stream.aclose()

    assert was_invalidated
    assert isinstance(book.current(), BestBidAsk)


@pytest.mark.asyncio
async def test_semantically_invalid_payload_is_rejected_before_reconnect() -> None:
    invalid_payload = json.loads(payload("level2_snapshot.json"))
    invalid_payload["events"][0]["updates"][0]["new_quantity"] = "-1"
    transport = ScriptedTransport([json.dumps(invalid_payload)])
    client = CoinbaseFeedClient(
        product_id="BTC-USD",
        transport_factory=ScriptedFactory([transport]),
        utc_now=lambda: RECEIVED_AT,
        connection_id_factory=lambda: "connection-1",
        sleep=_no_sleep,
    )

    events = await collect_until(
        client.events(),
        lambda event: event.state is FeedState.RECONNECTING,
    )

    assert events[-2].state is FeedState.INVALIDATED
    assert events[-2].reason == "malformed_message"
    assert events[-1].state is FeedState.RECONNECTING


@pytest.mark.asyncio
async def test_initial_snapshot_timeout_eventually_becomes_terminal() -> None:
    first = ScriptedTransport([with_sequence(payload("heartbeat.json"), 1)])
    second = ScriptedTransport([with_sequence(payload("heartbeat.json"), 10)])
    client = CoinbaseFeedClient(
        product_id="BTC-USD",
        transport_factory=ScriptedFactory([first, second]),
        utc_now=lambda: RECEIVED_AT,
        monotonic=ScriptedClock([0.0, 31.0, 100.0, 131.0]),
        connection_id_factory=iter(["one", "two"]).__next__,
        sleep=_no_sleep,
        initial_snapshot_timeout_seconds=30.0,
        startup_attempt_limit=2,
    )

    events = [event async for event in client.events()]

    assert [event.reason for event in events if event.state is FeedState.INVALIDATED] == [
        "initial_snapshot_timeout",
        "initial_snapshot_timeout",
    ]
    assert events[-1].state is FeedState.TERMINAL
    assert events[-1].reason == "initial_snapshot_timeout"


def test_backoff_progression_cap_and_jitter_boundaries() -> None:
    policy = BackoffPolicy(initial_seconds=1.0, cap_seconds=8.0, jitter_ratio=0.25)

    assert policy.delay(attempt=0, random_fraction=0.0) == 0.75
    assert policy.delay(attempt=1, random_fraction=0.5) == 2.0
    assert policy.delay(attempt=2, random_fraction=1.0) == 5.0
    assert policy.delay(attempt=10, random_fraction=1.0) == 8.0


async def _no_sleep(delay: float) -> None:
    del delay
