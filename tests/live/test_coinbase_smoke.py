import asyncio
import os

import pytest

from coinbase_insights.coinbase.client import CoinbaseFeedClient, FeedState
from coinbase_insights.coinbase.mapper import (
    MappedHeartbeatEnvelope,
    MappedLevel2Envelope,
    MappedSubscriptionEnvelope,
)
from coinbase_insights.domain.events import BookSnapshot, PriceLevelUpdate

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("COINBASE_LIVE_TEST") != "1",
        reason="set COINBASE_LIVE_TEST=1 to run the public-feed smoke test",
    ),
]


@pytest.mark.asyncio
async def test_public_feed_yields_snapshot_updates_heartbeat_and_acknowledgements() -> None:
    counts = {"snapshot": 0, "update": 0, "heartbeat": 0, "subscription": 0}
    events = CoinbaseFeedClient(product_id="BTC-USD").events()
    try:
        async with asyncio.timeout(20):
            async for event in events:
                assert event.state is not FeedState.INVALIDATED
                envelope = event.envelope
                if isinstance(envelope, MappedHeartbeatEnvelope):
                    counts["heartbeat"] += 1
                elif isinstance(envelope, MappedSubscriptionEnvelope):
                    counts["subscription"] += 1
                elif isinstance(envelope, MappedLevel2Envelope):
                    counts["snapshot"] += sum(
                        isinstance(item, BookSnapshot) for item in envelope.events
                    )
                    counts["update"] += sum(
                        isinstance(item, PriceLevelUpdate) for item in envelope.events
                    )
                if all(counts.values()):
                    break
    finally:
        await events.aclose()

    assert all(counts.values())
