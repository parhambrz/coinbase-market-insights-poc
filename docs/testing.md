# Testing and live verification

## Required deterministic checks

The required suite is network-free. It uses synthetic Coinbase-shaped fixtures, captured and sanitized public-feed fixtures, scripted transports, fake clocks, and deterministic forecasting inputs.

```bash
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

The live smoke test is excluded by default through an environment guard. Run it explicitly when internet access is available:

```bash
COINBASE_LIVE_TEST=1 uv run pytest --no-cov tests/live/test_coinbase_smoke.py -q
```

No credentials are required. `COINBASE_JWT` remains optional and was not exercised because no credentials were available.

## Test taxonomy

- Unit tests isolate domain state, calculations, forecasting policy, configuration, rendering, and reconnect decisions.
- Contract tests parse synthetic and sanitized Coinbase envelopes, then verify exact mapping into domain events.
- Integration tests join captured feed sequences to order-book recovery, sampling, forecasting, and output without opening a network connection.
- Live tests are optional compatibility checks against Coinbase. They are excluded from required local checks and CI because market and network availability are nondeterministic.

Runtime tests inject clocks and asynchronous sleep functions. They advance virtual UTC time directly, proving exact boundaries, no cumulative drift, and forecast maturity without wall-clock waits. Scripted transports control messages, disconnects, and timeout paths.

Hypothesis generates decimal price levels and update sequences for order-book properties that example tests can miss. These tests check invariants such as exact price identity, absolute replacement, deletion at zero, and agreement between the maintained best levels and a reference representation.

The configured coverage gate requires at least 80% branch coverage for `coinbase_insights`. Coverage is a regression signal, not evidence by itself: assertions target source semantics, invalid-state suppression, recovery, model fallbacks, and boundary conditions. Generated lines, live availability, and unstable numerical coefficients are not tested merely to increase the percentage.

## Captured fixture provenance

The files prefixed with `live_` under `tests/fixtures/coinbase/` were captured from the unauthenticated Coinbase Advanced Trade WebSocket on 2026-09-26:

- `live_subscriptions_2026-09-26.json`: complete subscription acknowledgement;
- `live_heartbeat_2026-09-26.json`: complete heartbeat, including Coinbase's Go-style `current_time` value;
- `live_level2_snapshot_2026-09-26.json`: one bid and one offer retained from a 41,385-level snapshot;
- `live_level2_update_2026-09-26.json`: two levels retained from a six-level update.

Truncated fixtures retain the original envelope and event shape and state the transformation in `_fixture_provenance`. The public payloads contained no credentials or account data.

Live verification discovered two compatibility requirements now covered by deterministic tests:

1. BTC-USD snapshots can exceed the `websockets` default 1 MiB message limit. The client uses a finite 8 MiB limit; the observed representative snapshot was 4,552,359 bytes.
2. `subscriptions` acknowledgements participate in the shared connection sequence, and heartbeat `current_time` uses a Go-style timestamp with nanoseconds and a monotonic suffix.

## Live observations

An unauthenticated BTC-USD run on 2026-09-26 verified:

- the production client received a snapshot, 546 level updates, two subscription acknowledgements, and a heartbeat without reconnecting;
- the CLI emitted 14 records on exact five-second boundaries over roughly 70 seconds;
- the one-minute average reached 12 samples;
- the first primary and naive 60-second forecast errors matured at the exact target;
- NDJSON remained isolated on stdout and diagnostics remained empty on stderr;
- both SIGINT and SIGTERM produced clean exit code 0.

A separate 10.126-second observation processed 182 envelopes and 1,310 price-level updates. The observed message rate was 17.974 envelopes/second and the snapshot contained 41,394 levels. Parse, map, apply, and BBO calculation measured 0.3009 ms median, 0.5925 ms p95, and 183.9109 ms maximum including the initial snapshot.

Twenty deterministic AutoReg fits over 180 observations measured 0.889 ms median and 2.461 ms maximum against the configured 2,000 ms timeout. A 20,000-observation history stress run retained 180 entries; history-scoped `tracemalloc` reported 59,436 current bytes and 59,860 peak bytes.

These are point-in-time observations from one machine and one market interval, not throughput or latency guarantees. Message rates, book depth, network conditions, and model timing will vary.

## Recovery evidence

Required tests inject disconnects, malformed messages, heartbeat expiry, sequence gaps/regressions, and updates before snapshots. Each failure invalidates current book state before reconnecting. Recorded-stream integration confirms numeric fields remain unavailable through a simulated gap and resume only after a fresh snapshot, so pre-gap state cannot be emitted as current data.
