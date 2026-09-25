---
name: part1-testing
description: "Design, write, run, or review tests for Coinbase challenge Part 1. Use for pytest structure, fixtures, fake time, pytest-asyncio, Hypothesis, unit/contract/integration boundaries, branch coverage, recorded-stream replay, test failures, or live smoke-test policy."
argument-hint: "Describe the behavior or test gap to cover"
user-invocable: true
disable-model-invocation: false
---

# Part 1 Testing

## Test taxonomy

- Unit tests exercise one domain, analytics, runtime, mapper, or renderer behavior without network access.
- Contract tests validate captured Coinbase payloads against boundary schemas and mapping.
- Integration tests compose internal components using recorded streams and a fake clock.
- Live Coinbase tests are optional manual/non-blocking smoke checks.

Follow [the expected test tree](../../plans/part-1-repository-structure.md) and the file-scoped test instructions.

## Workflow

1. State the observable behavior and cheapest test layer that can prove it.
2. Reproduce a bug with a failing focused test before changing production code when feasible.
3. Control time, randomness, network input, and model execution explicitly.
4. Use captured payload fixtures only for source-contract realism; prefer minimal builders for domain behavior.
5. Run the focused node ID, then its test directory, then the full suite.
6. Review branch coverage for untested failure behavior rather than chasing a percentage alone.

## Required risk coverage

- Snapshot replacement and absolute updates.
- Zero deletion and decimal price identity.
- Sequence gaps, heartbeat timeout, invalidation, and fresh-snapshot recovery.
- One-sided/crossed/stale books.
- Transient maximum spread and exact rolling-window edges.
- UTC-aligned scheduling without drift.
- Forecast warm-up, exact 60-second scoring, missing target, timeout, and naive fallback.
- stdout/stderr separation, NDJSON decimal serialization, and graceful shutdown.

## Quality bar

- No sleeps, internet dependence, test-order dependence, or shared mutable global state.
- Aim for at least 80% branch coverage as a warning threshold, with stronger coverage in domain and analytics.
- A test should fail for the intended behavioral regression, not incidental formatting or private implementation details.