---
name: coinbase-feed-development
description: "Develop or debug the Coinbase Advanced Trade WebSocket adapter for Part 1. Use for level2 and heartbeat subscriptions, Pydantic message contracts, source mapping, sequence continuity, reconnects, timeouts, captured feed fixtures, or feed health."
argument-hint: "Describe the Coinbase feed behavior or failure"
user-invocable: true
disable-model-invocation: false
---

# Coinbase Feed Development

## Ownership

Work primarily in `src/coinbase_insights/coinbase/` and its unit/contract tests. Read [the architecture](../../plans/part-1-poc-architecture.md) for source semantics and [the repository map](../../plans/part-1-repository-structure.md) for boundaries.

## Required behavior

- Connect to `wss://advanced-trade-ws.coinbase.com` and subscribe to `level2` for one product plus `heartbeats` on the same connection.
- Keep authentication optional; the public feed must work without signup.
- Validate the per-connection sequence across every received envelope, including heartbeats.
- Preserve source, server, event, and local receive timestamps with distinct names.
- Parse source decimal strings as `Decimal` and normalize `offer` to `ask` in the mapper, not in source contracts.
- Treat unknown extra fields as forward-compatible, but reject missing semantic fields and impossible values.
- On a gap, regression, stale heartbeat, malformed semantic message, or disconnect, invalidate downstream book state before reconnecting.
- Use capped exponential backoff with jitter and make it testable without sleeping.

## Workflow

1. Start from a captured payload, failing contract test, or connection-state transition.
2. Decide whether the behavior belongs to `messages.py`, `mapper.py`, or `client.py`.
3. Make the smallest adapter change without leaking Coinbase JSON shapes into the domain.
4. Run the focused unit or contract test immediately.
5. Run all Coinbase adapter tests, then recorded-stream integration tests.
6. Use a live connection only as an optional final smoke test.

## Completion checks

- Normal tests make no network calls.
- Recovery never allows pre-gap book state to remain healthy.
- Logs expose connection state without exposing JWTs.
- Captured fixtures remain faithful to the source payload.