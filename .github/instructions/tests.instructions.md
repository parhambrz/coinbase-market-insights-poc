---
name: "Part 1 Test Rules"
description: "Use when writing or modifying pytest tests, Coinbase fixtures, fake clocks, property-based tests, contract tests, or integration tests for Part 1."
applyTo: ["tests/**/*.py", "tests/fixtures/**"]
---

# Part 1 Test Rules

- Tests must be deterministic, isolated, and independent of internet access or current market activity.
- Name tests by observable behavior and condition, not by implementation method.
- Follow Arrange-Act-Assert when it improves readability; one test may contain multiple assertions about one coherent outcome.
- Use `Decimal` literals from strings and timezone-aware timestamps.
- Inject a fake clock for scheduler, rolling-window, forecast-maturity, timeout, and backoff tests. Never sleep in tests.
- Use captured Coinbase payloads for source contracts and synthetic minimal events for domain tests.
- Preserve raw fixture shape; fixtures must contain no credentials or invented fields presented as captured data.
- Use Hypothesis for order-book state transitions and invariants where example cases are insufficient.
- Unit and recorded-stream integration tests stay network-free. Mark optional live checks separately and exclude them from required CI.
- Coverage is diagnostic: prioritize sequence gaps, boundary timestamps, stale-state suppression, and fallback paths over trivial line coverage.