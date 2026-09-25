from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class Side(StrEnum):
    BID = "bid"
    ASK = "ask"


def _require_decimal(value: object, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        _require_decimal(self.price, "price")
        _require_decimal(self.quantity, "quantity")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.quantity <= 0:
            raise ValueError("snapshot quantity must be positive")


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    product_id: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    event_time: datetime

    def __post_init__(self) -> None:
        if not self.product_id:
            raise ValueError("product_id must not be empty")
        _require_aware(self.event_time, "event_time")


@dataclass(frozen=True, slots=True)
class PriceLevelUpdate:
    product_id: str
    side: Side
    price: Decimal
    quantity: Decimal
    event_time: datetime

    def __post_init__(self) -> None:
        if not self.product_id:
            raise ValueError("product_id must not be empty")
        _require_decimal(self.price, "price")
        _require_decimal(self.quantity, "quantity")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.quantity < 0:
            raise ValueError("update quantity must not be negative")
        _require_aware(self.event_time, "event_time")
