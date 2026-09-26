import asyncio
import json
import random
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from coinbase_insights.coinbase.mapper import (
    MappedEnvelope,
    MappedHeartbeatEnvelope,
    MappedLevel2Envelope,
    map_envelope,
)
from coinbase_insights.coinbase.messages import parse_envelope
from coinbase_insights.domain.events import BookSnapshot

COINBASE_WEBSOCKET_URL = "wss://advanced-trade-ws.coinbase.com"
MAX_MESSAGE_SIZE_BYTES = 8 * 1024 * 1024


class WebSocketTransport(Protocol):
    async def send(self, message: str) -> None: ...

    async def receive(self, *, timeout_seconds: float) -> str | bytes: ...

    async def close(self) -> None: ...


class TransportFactory(Protocol):
    async def __call__(self) -> WebSocketTransport: ...


class FeedState(StrEnum):
    CONNECTING = "connecting"
    AWAITING_SNAPSHOT = "awaiting_snapshot"
    HEALTHY = "healthy"
    INVALIDATED = "invalidated"
    RECONNECTING = "reconnecting"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class FeedEvent:
    connection_id: str
    state: FeedState
    reason: str | None = None
    envelope: MappedEnvelope | None = None
    invalidates_book: bool = False


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    initial_seconds: float = 1.0
    cap_seconds: float = 30.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.initial_seconds <= 0 or self.cap_seconds <= 0:
            raise ValueError("backoff durations must be positive")
        if self.initial_seconds > self.cap_seconds:
            raise ValueError("initial backoff must not exceed cap")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between zero and one")

    def delay(self, *, attempt: int, random_fraction: float) -> float:
        if attempt < 0:
            raise ValueError("attempt must not be negative")
        if not 0 <= random_fraction <= 1:
            raise ValueError("random_fraction must be between zero and one")
        base = min(self.cap_seconds, self.initial_seconds * (2**attempt))
        factor = 1 - self.jitter_ratio + (2 * self.jitter_ratio * random_fraction)
        return min(self.cap_seconds, base * factor)


class _ConnectionFailure(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _SequenceTracker:
    def __init__(self) -> None:
        self._last: int | None = None

    def observe(self, sequence: int) -> None:
        if self._last is None:
            self._last = sequence
            return
        expected = self._last + 1
        if sequence == expected:
            self._last = sequence
            return
        reason = "sequence_gap" if sequence > expected else "sequence_regression"
        raise _ConnectionFailure(reason)


class CoinbaseFeedClient:
    def __init__(
        self,
        *,
        product_id: str,
        jwt: str | None = None,
        transport_factory: TransportFactory | None = None,
        heartbeat_timeout_seconds: float = 15.0,
        initial_snapshot_timeout_seconds: float = 30.0,
        startup_attempt_limit: int = 3,
        backoff: BackoffPolicy | None = None,
        utc_now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        connection_id_factory: Callable[[], str] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        if not product_id:
            raise ValueError("product_id must not be empty")
        if heartbeat_timeout_seconds <= 0 or initial_snapshot_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if startup_attempt_limit <= 0:
            raise ValueError("startup_attempt_limit must be positive")
        self._product_id = product_id
        self._jwt = jwt
        self._transport_factory = transport_factory or WebsocketsTransportFactory()
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._initial_snapshot_timeout_seconds = initial_snapshot_timeout_seconds
        self._startup_attempt_limit = startup_attempt_limit
        self._backoff = backoff or BackoffPolicy()
        self._utc_now = utc_now or _utc_now
        self._monotonic = monotonic or time.monotonic
        self._connection_id_factory = connection_id_factory or _connection_id
        self._sleep = sleep or asyncio.sleep
        self._jitter = jitter or random.random

    async def events(self) -> AsyncGenerator[FeedEvent]:
        startup_failures = 0
        reconnect_attempt = 0
        while True:
            connection_id = self._connection_id_factory()
            yield FeedEvent(
                connection_id=connection_id,
                state=FeedState.CONNECTING,
                invalidates_book=True,
            )
            transport: WebSocketTransport | None = None
            snapshot_received = False
            try:
                transport = await self._transport_factory()
                for subscription in build_subscription_messages(
                    product_id=self._product_id,
                    jwt=self._jwt,
                ):
                    await transport.send(subscription)
                connection_started = self._monotonic()
                yield FeedEvent(
                    connection_id=connection_id,
                    state=FeedState.AWAITING_SNAPSHOT,
                    invalidates_book=True,
                )
                sequence = _SequenceTracker()
                last_heartbeat_at = connection_started
                current_monotonic = connection_started
                while True:
                    heartbeat_remaining = self._heartbeat_timeout_seconds - (
                        current_monotonic - last_heartbeat_at
                    )
                    if heartbeat_remaining <= 0:
                        raise _ConnectionFailure("heartbeat_timeout")
                    raw_message = await transport.receive(timeout_seconds=heartbeat_remaining)
                    envelope = map_envelope(
                        parse_envelope(raw_message),
                        received_at=self._utc_now(),
                    )
                    sequence.observe(envelope.source_sequence)
                    current_monotonic = self._monotonic()
                    if isinstance(envelope, MappedHeartbeatEnvelope):
                        last_heartbeat_at = current_monotonic
                    elif current_monotonic - last_heartbeat_at >= self._heartbeat_timeout_seconds:
                        raise _ConnectionFailure("heartbeat_timeout")
                    if not snapshot_received:
                        if _contains_snapshot(envelope, product_id=self._product_id):
                            snapshot_received = True
                            startup_failures = 0
                            reconnect_attempt = 0
                        elif isinstance(envelope, MappedLevel2Envelope):
                            raise _ConnectionFailure("update_before_snapshot")
                        elif (
                            current_monotonic - connection_started
                            >= self._initial_snapshot_timeout_seconds
                        ):
                            raise _ConnectionFailure("initial_snapshot_timeout")
                    yield FeedEvent(
                        connection_id=connection_id,
                        state=(
                            FeedState.HEALTHY if snapshot_received else FeedState.AWAITING_SNAPSHOT
                        ),
                        envelope=envelope,
                    )
            except _ConnectionFailure as error:
                reason = error.reason
            except TimeoutError:
                reason = "heartbeat_timeout"
            except (ValidationError, ValueError, json.JSONDecodeError):
                reason = "malformed_message"
            except (ConnectionError, OSError, WebSocketException):
                reason = "disconnected"
            finally:
                if transport is not None:
                    await transport.close()

            yield FeedEvent(
                connection_id=connection_id,
                state=FeedState.INVALIDATED,
                reason=reason,
                invalidates_book=True,
            )
            if not snapshot_received:
                startup_failures += 1
                if startup_failures >= self._startup_attempt_limit:
                    yield FeedEvent(
                        connection_id=connection_id,
                        state=FeedState.TERMINAL,
                        reason=reason,
                        invalidates_book=True,
                    )
                    return
            delay = self._backoff.delay(
                attempt=reconnect_attempt,
                random_fraction=self._jitter(),
            )
            yield FeedEvent(
                connection_id=connection_id,
                state=FeedState.RECONNECTING,
                reason=reason,
                invalidates_book=True,
            )
            await self._sleep(delay)
            reconnect_attempt += 1


class _WebsocketsTransport:
    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection

    async def send(self, message: str) -> None:
        await self._connection.send(message)

    async def receive(self, *, timeout_seconds: float) -> str | bytes:
        return await asyncio.wait_for(self._connection.recv(), timeout=timeout_seconds)

    async def close(self) -> None:
        await self._connection.close()


class WebsocketsTransportFactory:
    async def __call__(self) -> WebSocketTransport:
        connection = await connect(
            COINBASE_WEBSOCKET_URL,
            ping_interval=None,
            max_size=MAX_MESSAGE_SIZE_BYTES,
        )
        return _WebsocketsTransport(connection)


def build_subscription_messages(*, product_id: str, jwt: str | None) -> tuple[str, str]:
    level2: dict[str, object] = {
        "type": "subscribe",
        "channel": "level2",
        "product_ids": [product_id],
    }
    heartbeats: dict[str, object] = {
        "type": "subscribe",
        "channel": "heartbeats",
    }
    if jwt is not None:
        level2["jwt"] = jwt
        heartbeats["jwt"] = jwt
    return (
        json.dumps(level2, separators=(",", ":")),
        json.dumps(heartbeats, separators=(",", ":")),
    )


def _contains_snapshot(envelope: MappedEnvelope, *, product_id: str) -> bool:
    return isinstance(envelope, MappedLevel2Envelope) and any(
        isinstance(event, BookSnapshot) and event.product_id == product_id
        for event in envelope.events
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _connection_id() -> str:
    return str(uuid4())
