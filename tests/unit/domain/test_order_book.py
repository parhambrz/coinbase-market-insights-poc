from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from coinbase_insights.domain.events import BookLevel, BookSnapshot, PriceLevelUpdate, Side
from coinbase_insights.domain.models import BestBidAsk, BookUnavailable
from coinbase_insights.domain.order_book import OrderBook, OrderBookNotReadyError

PRODUCT_ID = "BTC-USD"
EVENT_TIME = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def level(price: str, quantity: str) -> BookLevel:
    return BookLevel(price=Decimal(price), quantity=Decimal(quantity))


def snapshot(
    *,
    bids: tuple[BookLevel, ...] = (BookLevel(Decimal("100"), Decimal("2")),),
    asks: tuple[BookLevel, ...] = (BookLevel(Decimal("101"), Decimal("3")),),
    event_time: datetime = EVENT_TIME,
) -> BookSnapshot:
    return BookSnapshot(
        product_id=PRODUCT_ID,
        bids=bids,
        asks=asks,
        event_time=event_time,
    )


def best_bid_ask(book: OrderBook) -> BestBidAsk:
    current = book.current()
    assert isinstance(current, BestBidAsk)
    return current


def test_snapshot_creates_best_bid_and_ask_with_quantities() -> None:
    book = OrderBook(PRODUCT_ID)

    book.apply_snapshot(
        snapshot(
            bids=(level("99", "1"), level("100", "2")),
            asks=(level("102", "4"), level("101", "3")),
        )
    )

    current = best_bid_ask(book)
    assert current.product_id == PRODUCT_ID
    assert current.bid_price == Decimal("100")
    assert current.bid_quantity == Decimal("2")
    assert current.ask_price == Decimal("101")
    assert current.ask_quantity == Decimal("3")
    assert current.event_time == EVENT_TIME


def test_new_snapshot_atomically_replaces_previous_levels() -> None:
    book = OrderBook(PRODUCT_ID)
    book.apply_snapshot(snapshot())

    book.apply_snapshot(
        snapshot(
            bids=(level("90", "5"),),
            asks=(level("110", "6"),),
            event_time=EVENT_TIME + timedelta(seconds=1),
        )
    )

    current = best_bid_ask(book)
    assert current.bid_price == Decimal("90")
    assert current.ask_price == Decimal("110")
    assert current.event_time == EVENT_TIME + timedelta(seconds=1)


def test_update_replaces_absolute_quantity_instead_of_adding() -> None:
    book = OrderBook(PRODUCT_ID)
    book.apply_snapshot(snapshot())

    book.apply_update(
        PriceLevelUpdate(
            product_id=PRODUCT_ID,
            side=Side.BID,
            price=Decimal("100"),
            quantity=Decimal("7"),
            event_time=EVENT_TIME + timedelta(seconds=1),
        )
    )

    assert best_bid_ask(book).bid_quantity == Decimal("7")


def test_zero_quantity_deletes_level_and_absent_deletion_is_idempotent() -> None:
    book = OrderBook(PRODUCT_ID)
    book.apply_snapshot(snapshot(bids=(level("99", "1"), level("100", "2"))))
    deletion = PriceLevelUpdate(
        product_id=PRODUCT_ID,
        side=Side.BID,
        price=Decimal("100"),
        quantity=Decimal("0"),
        event_time=EVENT_TIME + timedelta(seconds=1),
    )

    book.apply_update(deletion)
    book.apply_update(deletion)

    current = best_bid_ask(book)
    assert current.bid_price == Decimal("99")
    assert current.bid_quantity == Decimal("1")


def test_best_levels_change_after_insert_and_delete() -> None:
    book = OrderBook(PRODUCT_ID)
    book.apply_snapshot(snapshot())

    book.apply_update(
        PriceLevelUpdate(
            product_id=PRODUCT_ID,
            side=Side.ASK,
            price=Decimal("100.5"),
            quantity=Decimal("4"),
            event_time=EVENT_TIME + timedelta(seconds=1),
        )
    )
    assert best_bid_ask(book).ask_price == Decimal("100.5")

    book.apply_update(
        PriceLevelUpdate(
            product_id=PRODUCT_ID,
            side=Side.ASK,
            price=Decimal("100.5"),
            quantity=Decimal("0"),
            event_time=EVENT_TIME + timedelta(seconds=2),
        )
    )
    assert best_bid_ask(book).ask_price == Decimal("101")


def test_decimal_price_levels_that_float_would_collapse_remain_distinct() -> None:
    lower_price = Decimal("100.000000000000000001")
    higher_price = Decimal("100.000000000000000002")
    book = OrderBook(PRODUCT_ID)

    book.apply_snapshot(
        snapshot(
            bids=(
                BookLevel(lower_price, Decimal("1")),
                BookLevel(higher_price, Decimal("2")),
            ),
            asks=(level("101", "1"),),
        )
    )

    current = best_bid_ask(book)
    assert current.bid_price == higher_price
    assert current.bid_quantity == Decimal("2")


@pytest.mark.parametrize(
    ("bids", "asks"),
    [
        ((), ()),
        ((BookLevel(Decimal("100"), Decimal("1")),), ()),
        ((), (BookLevel(Decimal("101"), Decimal("1")),)),
        (
            (BookLevel(Decimal("102"), Decimal("1")),),
            (BookLevel(Decimal("101"), Decimal("1")),),
        ),
    ],
)
def test_empty_one_sided_and_crossed_books_are_unavailable(
    bids: tuple[BookLevel, ...], asks: tuple[BookLevel, ...]
) -> None:
    book = OrderBook(PRODUCT_ID)

    book.apply_snapshot(snapshot(bids=bids, asks=asks))

    assert isinstance(book.current(), BookUnavailable)


def test_invalidation_suppresses_state_until_a_new_snapshot() -> None:
    book = OrderBook(PRODUCT_ID)
    book.apply_snapshot(snapshot())

    book.invalidate()

    assert isinstance(book.current(), BookUnavailable)
    with pytest.raises(OrderBookNotReadyError):
        book.apply_update(
            PriceLevelUpdate(
                product_id=PRODUCT_ID,
                side=Side.BID,
                price=Decimal("100"),
                quantity=Decimal("9"),
                event_time=EVENT_TIME + timedelta(seconds=1),
            )
        )

    book.apply_snapshot(snapshot(event_time=EVENT_TIME + timedelta(seconds=2)))
    assert isinstance(book.current(), BestBidAsk)


def test_returned_best_bid_ask_is_immutable() -> None:
    book = OrderBook(PRODUCT_ID)
    book.apply_snapshot(snapshot())
    current = best_bid_ask(book)
    bid_price_field = "bid_price"

    with pytest.raises(FrozenInstanceError):
        setattr(current, bid_price_field, Decimal("0"))


side_strategy = st.sampled_from([Side.BID, Side.ASK])
price_strategy = st.integers(min_value=95, max_value=105).map(Decimal)
quantity_strategy = st.integers(min_value=0, max_value=5).map(Decimal)


@given(
    st.lists(
        st.tuples(side_strategy, price_strategy, quantity_strategy),
        max_size=50,
    )
)
def test_random_updates_match_reference_book(
    updates: list[tuple[Side, Decimal, Decimal]],
) -> None:
    book = OrderBook(PRODUCT_ID)
    book.apply_snapshot(snapshot())
    reference_bids = {Decimal("100"): Decimal("2")}
    reference_asks = {Decimal("101"): Decimal("3")}

    for index, (side, price, quantity) in enumerate(updates, start=1):
        book.apply_update(
            PriceLevelUpdate(
                product_id=PRODUCT_ID,
                side=side,
                price=price,
                quantity=quantity,
                event_time=EVENT_TIME + timedelta(microseconds=index),
            )
        )
        reference_side = reference_bids if side is Side.BID else reference_asks
        if quantity == 0:
            reference_side.pop(price, None)
        else:
            reference_side[price] = quantity

        current = book.current()
        if reference_bids and reference_asks and max(reference_bids) <= min(reference_asks):
            assert isinstance(current, BestBidAsk)
            assert current.bid_price == max(reference_bids)
            assert current.bid_quantity == reference_bids[current.bid_price]
            assert current.ask_price == min(reference_asks)
            assert current.ask_quantity == reference_asks[current.ask_price]
        else:
            assert isinstance(current, BookUnavailable)
