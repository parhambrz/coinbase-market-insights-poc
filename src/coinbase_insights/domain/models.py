from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class BookUnavailableReason(StrEnum):
    NOT_INITIALIZED = "not_initialized"
    INVALIDATED = "invalidated"
    EMPTY_BIDS = "empty_bids"
    EMPTY_ASKS = "empty_asks"
    CROSSED = "crossed"


@dataclass(frozen=True, slots=True)
class BookUnavailable:
    product_id: str
    reason: BookUnavailableReason
    event_time: datetime | None


@dataclass(frozen=True, slots=True)
class BestBidAsk:
    product_id: str
    bid_price: Decimal
    bid_quantity: Decimal
    ask_price: Decimal
    ask_quantity: Decimal
    event_time: datetime


BookState = BestBidAsk | BookUnavailable
