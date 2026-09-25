---
name: market-metrics-development
description: "Develop or debug Part 1 streaming metrics and runtime sampling. Use for five-second UTC boundaries, bounded histories, spread and maximum spread, mid-price, rolling 1/5/15-minute averages, forecast-error windows, freshness, fake clocks, or sampler orchestration."
argument-hint: "Describe the metric, window, or sampler behavior"
user-invocable: true
disable-model-invocation: false
---

# Market Metrics Development

## Ownership

Work in `analytics/metrics.py`, `runtime/history.py`, `runtime/sampler.py`, and their tests. Metrics consume immutable domain observations and contain no WebSocket or rendering logic.

## Semantics

- Spread is `lowest_ask - highest_bid`; mid-price is their decimal average.
- Update process-lifetime maximum spread on every valid BBO change, not only sampled output.
- Sample on UTC-aligned five-second boundaries using monotonic elapsed-time scheduling to avoid drift.
- Rolling windows include timestamps in $(t-W, t]$ and expose sample counts.
- Use bounded timestamped deques and prune expired entries in amortized $O(1)$ time.
- Unhealthy, stale, one-sided, or crossed books produce unavailable observations and never enter numeric windows.
- Mature forecast errors only at their exact valid target boundary.

## Workflow

1. Write the time boundary and expected included observations explicitly.
2. Use an injected fake clock; never use real sleeps in tests.
3. Implement pure calculations separately from sampler orchestration.
4. Run the exact boundary test first.
5. Run metrics, history, sampler, and forecasting tests together.

## Review checks

- Startup partial windows are distinguishable through sample counts.
- Scheduling work does not accumulate five-second drift.
- History is bounded during indefinite operation.
- Missing data is not forward-filled across feed gaps.