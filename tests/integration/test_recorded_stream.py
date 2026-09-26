import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any, cast

import pytest

from coinbase_insights.coinbase.client import CoinbaseFeedClient, FeedState
from coinbase_insights.output.ndjson import write_ndjson
from coinbase_insights.runtime.sampler import RuntimeSampler

FIXTURES = Path(__file__).parents[1] / "fixtures" / "coinbase"


class RecordedTransport:
    def __init__(self, messages: list[str]) -> None:
        self._messages = iter(messages)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def receive(self, *, timeout_seconds: float) -> str:
        del timeout_seconds
        return next(self._messages)

    async def close(self) -> None:
        self.closed = True


class RecordedFactory:
    def __init__(self, transports: list[RecordedTransport]) -> None:
        self._transports = iter(transports)

    async def __call__(self) -> RecordedTransport:
        return next(self._transports)


def fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / name).read_text()))


def message(payload: dict[str, Any], *, sequence: int) -> str:
    payload["sequence_num"] = sequence
    return json.dumps(payload)


def ask_update(*, sequence: int, price: str, quantity: str, second: int) -> str:
    return json.dumps(
        {
            "channel": "l2_data",
            "timestamp": f"2026-09-25T12:00:{second:02d}.500000Z",
            "sequence_num": sequence,
            "events": [
                {
                    "type": "update",
                    "product_id": "BTC-USD",
                    "updates": [
                        {
                            "side": "offer",
                            "event_time": f"2026-09-25T12:00:{second:02d}Z",
                            "price_level": price,
                            "new_quantity": quantity,
                        }
                    ],
                }
            ],
            "_fixture_provenance": "synthetic: recorded-stream integration",
        }
    )


@pytest.mark.asyncio
async def test_recorded_stream_is_deterministic_across_gap_and_recovery() -> None:
    first = RecordedTransport(
        [
            message(fixture("heartbeat.json"), sequence=99),
            message(fixture("level2_snapshot.json"), sequence=100),
            message(fixture("level2_updates.jsonl"), sequence=101),
            ask_update(sequence=102, price="110", quantity="1", second=10),
            ask_update(sequence=103, price="101.000000000000000002", quantity="4", second=11),
            message(fixture("heartbeat.json"), sequence=105),
        ]
    )
    second = RecordedTransport([message(fixture("level2_snapshot.json"), sequence=200)])
    received_times = iter(
        datetime(2026, 9, 25, 12, 0, second, 600_000, tzinfo=UTC)
        for second in (0, 1, 6, 10, 11, 16, 21)
    )

    async def no_sleep(delay: float) -> None:
        del delay

    client = CoinbaseFeedClient(
        product_id="BTC-USD",
        transport_factory=RecordedFactory([first, second]),
        utc_now=received_times.__next__,
        connection_id_factory=iter(["first", "second"]).__next__,
        sleep=no_sleep,
        jitter=lambda: 0.5,
    )
    sampler = RuntimeSampler(product_id="BTC-USD")
    stream = StringIO()
    sample_times_by_sequence = {
        100: datetime(2026, 9, 25, 12, 0, 5, tzinfo=UTC),
        101: datetime(2026, 9, 25, 12, 0, 10, tzinfo=UTC),
        103: datetime(2026, 9, 25, 12, 0, 15, tzinfo=UTC),
        200: datetime(2026, 9, 25, 12, 0, 25, tzinfo=UTC),
    }

    events = client.events()
    async for feed_event in events:
        sampler.consume(feed_event)
        if feed_event.state is FeedState.CONNECTING and feed_event.connection_id == "first":
            write_ndjson(
                await sampler.sample_at(datetime(2026, 9, 25, 12, 0, tzinfo=UTC)),
                stream=stream,
            )
        if feed_event.envelope is not None:
            sampled_at = sample_times_by_sequence.get(feed_event.envelope.source_sequence)
            if sampled_at is not None:
                write_ndjson(await sampler.sample_at(sampled_at), stream=stream)
        if feed_event.state is FeedState.INVALIDATED:
            write_ndjson(
                await sampler.sample_at(datetime(2026, 9, 25, 12, 0, 20, tzinfo=UTC)),
                stream=stream,
            )
        if feed_event.connection_id == "second" and feed_event.state is FeedState.HEALTHY:
            break
    await events.aclose()

    records = [cast(dict[str, Any], json.loads(line)) for line in stream.getvalue().splitlines()]
    assert [record["as_of"] for record in records] == [
        "2026-09-25T12:00:00Z",
        "2026-09-25T12:00:05Z",
        "2026-09-25T12:00:10Z",
        "2026-09-25T12:00:15Z",
        "2026-09-25T12:00:20Z",
        "2026-09-25T12:00:25Z",
    ]
    assert records[0]["highest_bid"] is None
    assert records[1]["highest_bid"] == {
        "price": "100.000000000000000001",
        "quantity": "2.5",
    }
    assert records[2]["feed_status"] == "feed_stale"
    assert records[2]["reason"] == "invalid_book"
    assert records[2]["current_spread"] is None
    assert records[3]["current_spread"] == "1.000000000000000001"
    assert records[3]["max_spread_since_start"] == "9.999999999999999999"
    assert records[3]["highest_bid"]["quantity"] == "4.25"
    assert records[3]["lowest_ask"]["quantity"] == "4"
    assert records[3]["average_mid_price"]["1m"]["samples"] == 2
    assert records[4]["reason"] == "sequence_gap"
    assert records[4]["highest_bid"] is None
    assert records[5]["highest_bid"] == records[1]["highest_bid"]
    assert records[5]["average_mid_price"]["15m"]["samples"] == 3
    assert first.closed
    assert second.closed
