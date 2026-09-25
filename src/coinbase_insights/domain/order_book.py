from decimal import Decimal

from sortedcontainers import SortedDict

from coinbase_insights.domain.events import BookSnapshot, PriceLevelUpdate, Side
from coinbase_insights.domain.models import (
    BestBidAsk,
    BookState,
    BookUnavailable,
    BookUnavailableReason,
)


class OrderBookNotReadyError(RuntimeError):
    pass


class OrderBook:
    def __init__(self, product_id: str) -> None:
        if not product_id:
            raise ValueError("product_id must not be empty")
        self._product_id = product_id
        self._bids: SortedDict[Decimal, Decimal] = SortedDict()
        self._asks: SortedDict[Decimal, Decimal] = SortedDict()
        self._is_usable = False
        self._unavailable_reason = BookUnavailableReason.NOT_INITIALIZED
        self._event_time = None

    def apply_snapshot(self, snapshot: BookSnapshot) -> None:
        self._require_product(snapshot.product_id)
        replacement_bids = SortedDict((level.price, level.quantity) for level in snapshot.bids)
        replacement_asks = SortedDict((level.price, level.quantity) for level in snapshot.asks)

        self._bids = replacement_bids
        self._asks = replacement_asks
        self._event_time = snapshot.event_time
        self._is_usable = True

    def apply_update(self, update: PriceLevelUpdate) -> None:
        self._require_product(update.product_id)
        if not self._is_usable:
            raise OrderBookNotReadyError("a fresh snapshot is required before updates")

        levels = self._bids if update.side is Side.BID else self._asks
        if update.quantity == 0:
            levels.pop(update.price, None)
        else:
            levels[update.price] = update.quantity
        self._event_time = update.event_time

    def invalidate(self) -> None:
        self._bids.clear()
        self._asks.clear()
        self._is_usable = False
        self._unavailable_reason = BookUnavailableReason.INVALIDATED

    def current(self) -> BookState:
        if not self._is_usable:
            return self._unavailable(self._unavailable_reason)
        if not self._bids:
            return self._unavailable(BookUnavailableReason.EMPTY_BIDS)
        if not self._asks:
            return self._unavailable(BookUnavailableReason.EMPTY_ASKS)

        bid_price, bid_quantity = self._bids.peekitem(-1)
        ask_price, ask_quantity = self._asks.peekitem(0)
        if bid_price > ask_price:
            return self._unavailable(BookUnavailableReason.CROSSED)

        if self._event_time is None:
            raise RuntimeError("usable order book has no event timestamp")
        return BestBidAsk(
            product_id=self._product_id,
            bid_price=bid_price,
            bid_quantity=bid_quantity,
            ask_price=ask_price,
            ask_quantity=ask_quantity,
            event_time=self._event_time,
        )

    def _unavailable(self, reason: BookUnavailableReason) -> BookUnavailable:
        return BookUnavailable(
            product_id=self._product_id,
            reason=reason,
            event_time=self._event_time,
        )

    def _require_product(self, product_id: str) -> None:
        if product_id != self._product_id:
            raise ValueError(f"event product {product_id!r} does not match {self._product_id!r}")
