from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


class CoinbaseMessage(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class Level2Update(CoinbaseMessage):
    side: Literal["bid", "offer"]
    event_time: AwareDatetime
    price_level: str
    new_quantity: str

    @field_validator("price_level")
    @classmethod
    def validate_price_level(cls, value: str) -> str:
        decimal_value = _parse_decimal(value, "price_level")
        if decimal_value <= 0:
            raise ValueError("price_level must be positive")
        return value

    @field_validator("new_quantity")
    @classmethod
    def validate_new_quantity(cls, value: str) -> str:
        decimal_value = _parse_decimal(value, "new_quantity")
        if decimal_value < 0:
            raise ValueError("new_quantity must not be negative")
        return value


class Level2Event(CoinbaseMessage):
    type: Literal["snapshot", "update"]
    product_id: Annotated[str, Field(min_length=1)]
    updates: Annotated[tuple[Level2Update, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_snapshot(self) -> "Level2Event":
        if self.type != "snapshot":
            return self
        if any(Decimal(update.new_quantity) == 0 for update in self.updates):
            raise ValueError("snapshot quantities must be positive")
        event_times = {update.event_time for update in self.updates}
        if len(event_times) != 1:
            raise ValueError("snapshot updates must share one event_time")
        return self


class Level2Envelope(CoinbaseMessage):
    channel: Literal["l2_data"]
    timestamp: AwareDatetime
    sequence_num: Annotated[int, Field(ge=0)]
    events: Annotated[tuple[Level2Event, ...], Field(min_length=1)]


class HeartbeatEvent(CoinbaseMessage):
    current_time: AwareDatetime
    heartbeat_counter: Annotated[int, Field(ge=0)]


class HeartbeatEnvelope(CoinbaseMessage):
    channel: Literal["heartbeats"]
    timestamp: AwareDatetime
    sequence_num: Annotated[int, Field(ge=0)]
    events: Annotated[tuple[HeartbeatEvent, ...], Field(min_length=1)]


type Envelope = Annotated[
    Level2Envelope | HeartbeatEnvelope,
    Field(discriminator="channel"),
]
_ENVELOPE_ADAPTER: TypeAdapter[Envelope] = TypeAdapter(Envelope)


def parse_envelope(raw_message: str | bytes) -> Envelope:
    return _ENVELOPE_ADAPTER.validate_json(raw_message)


def _parse_decimal(value: str, field_name: str) -> Decimal:
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field_name} must be a decimal string") from error
    if not decimal_value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return decimal_value
