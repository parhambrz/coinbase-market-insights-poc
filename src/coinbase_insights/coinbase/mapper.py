from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from coinbase_insights.coinbase.messages import (
    Envelope,
    HeartbeatEnvelope,
    Level2Event,
    SubscriptionEnvelope,
)
from coinbase_insights.domain.events import BookLevel, BookSnapshot, PriceLevelUpdate, Side

type DomainBookEvent = BookSnapshot | PriceLevelUpdate
type LiteralSide = Literal["bid", "offer"]


@dataclass(frozen=True, slots=True)
class HeartbeatSignal:
    current_time: datetime
    counter: int


@dataclass(frozen=True, slots=True)
class MappedLevel2Envelope:
    source_sequence: int
    server_time: datetime
    received_at: datetime
    events: tuple[DomainBookEvent, ...]


@dataclass(frozen=True, slots=True)
class MappedHeartbeatEnvelope:
    source_sequence: int
    server_time: datetime
    received_at: datetime
    heartbeats: tuple[HeartbeatSignal, ...]


@dataclass(frozen=True, slots=True)
class SubscriptionSignal:
    channel: str
    product_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MappedSubscriptionEnvelope:
    source_sequence: int
    server_time: datetime
    received_at: datetime
    subscriptions: tuple[SubscriptionSignal, ...]


type MappedEnvelope = MappedLevel2Envelope | MappedHeartbeatEnvelope | MappedSubscriptionEnvelope


def map_envelope(envelope: Envelope, *, received_at: datetime) -> MappedEnvelope:
    _require_aware(received_at)
    if isinstance(envelope, HeartbeatEnvelope):
        return MappedHeartbeatEnvelope(
            source_sequence=envelope.sequence_num,
            server_time=envelope.timestamp,
            received_at=received_at,
            heartbeats=tuple(
                HeartbeatSignal(
                    current_time=heartbeat.current_time,
                    counter=heartbeat.heartbeat_counter,
                )
                for heartbeat in envelope.events
            ),
        )
    if isinstance(envelope, SubscriptionEnvelope):
        return MappedSubscriptionEnvelope(
            source_sequence=envelope.sequence_num,
            server_time=envelope.timestamp,
            received_at=received_at,
            subscriptions=tuple(
                SubscriptionSignal(channel=channel, product_ids=product_ids)
                for event in envelope.events
                for channel, product_ids in event.subscriptions.items()
            ),
        )

    return MappedLevel2Envelope(
        source_sequence=envelope.sequence_num,
        server_time=envelope.timestamp,
        received_at=received_at,
        events=tuple(
            mapped_event
            for source_event in envelope.events
            for mapped_event in _map_level2_event(source_event)
        ),
    )


def _map_level2_event(event: Level2Event) -> tuple[DomainBookEvent, ...]:
    if event.type == "snapshot":
        return (_map_snapshot(event),)
    return tuple(
        PriceLevelUpdate(
            product_id=event.product_id,
            side=_map_side(update.side),
            price=Decimal(update.price_level),
            quantity=Decimal(update.new_quantity),
            event_time=update.event_time,
        )
        for update in event.updates
    )


def _map_snapshot(event: Level2Event) -> BookSnapshot:
    bids: list[BookLevel] = []
    asks: list[BookLevel] = []
    for update in event.updates:
        level = BookLevel(
            price=Decimal(update.price_level),
            quantity=Decimal(update.new_quantity),
        )
        if update.side == "bid":
            bids.append(level)
        else:
            asks.append(level)
    return BookSnapshot(
        product_id=event.product_id,
        bids=tuple(bids),
        asks=tuple(asks),
        event_time=event.updates[0].event_time,
    )


def _map_side(side: LiteralSide) -> Side:
    return Side.BID if side == "bid" else Side.ASK


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
