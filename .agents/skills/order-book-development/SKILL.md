---
name: order-book-development
description: "Develop, test, or review Part 1 order-book domain behavior. Use for snapshots, absolute price-level updates, zero-quantity deletion, Decimal precision, SortedDict state, best bid/ask, spread transitions, book validity, or order-book invariants."
argument-hint: "Describe the order-book rule or failing invariant"
user-invocable: true
disable-model-invocation: false
---

# Order Book Development

## Ownership

Work primarily in `src/coinbase_insights/domain/` and `tests/unit/domain/`. The domain imports no Coinbase, CLI, renderer, or forecasting adapters.

## Invariants

- Prices and quantities are `Decimal` values created from strings.
- A snapshot atomically replaces both prior sides.
- An update sets the absolute quantity; it is never added as a delta.
- Zero quantity removes the level.
- Best bid is the maximum bid; best ask is the minimum ask.
- A usable BBO requires both sides, positive quantities, and `best_bid <= best_ask`.
- The book is unusable before a current-connection snapshot and after invalidation.
- A BBO snapshot returned to other layers is immutable.

## Workflow

1. Express the behavior as an invariant or state transition.
2. Add a minimal deterministic example test.
3. Change the owning domain method only.
4. Run the focused test.
5. Add or update Hypothesis comparison against a slow dictionary/reference implementation when the state space matters.
6. Run all domain and metrics tests to catch downstream semantic changes.

## Review checks

- Updates remain $O(\log n)$ through sorted maps.
- Snapshot application cannot expose half-replaced state.
- No adapter concerns or async I/O enter the domain.
- Invalid books produce explicit unavailable state, not fabricated zero values.