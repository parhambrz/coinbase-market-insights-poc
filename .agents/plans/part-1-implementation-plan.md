# Part 1 Implementation Plan

## 1. Purpose

Implement the Coinbase market-insights proof of concept described in [the accepted architecture](./part-1-poc-architecture.md), using [the repository ownership map](./part-1-repository-structure.md).

The plan is ordered by dependency and risk, not by presentation value:

1. establish a reproducible Python project;
2. prove exact order-book state transitions;
3. validate the external Coinbase contract;
4. prove time-window and forecast semantics with fake time;
5. compose a deterministic offline application;
6. add the live WebSocket and recovery loop;
7. package, automate, document, and perform final live verification.

Do not create the full directory tree up front. Add a module when its owning milestone starts so the repository contains working slices rather than empty placeholders.

## 2. Delivery rules

- Complete milestones in order unless a concrete dependency requires a small adjustment.
- Keep each edit focused on one behavioral slice and run the narrowest relevant test immediately afterward.
- All required automated tests are network-free and deterministic.
- Use `Decimal` for every price, quantity, spread, mid-price, forecast, and error value.
- Use timezone-aware UTC datetimes for event labels and an injected monotonic clock for elapsed-time behavior.
- Never emit current metrics before a valid snapshot or after connection continuity is lost.
- Keep naive persistence available before introducing AutoReg; model failure must never stop feed processing or output.
- No API key is required. Optional Coinbase JWT support must not block unauthenticated operation.
- Do not introduce Part 2 infrastructure.

## 3. Standard local checks

Once the corresponding tooling exists, use these commands consistently in local development, documentation, and CI:

```bash
uv sync --frozen --all-groups
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

During implementation, prefer a focused test first, for example:

```bash
uv run pytest tests/unit/domain/test_order_book.py -q
uv run pytest tests/unit/analytics/test_metrics.py -q
uv run pytest tests/integration/test_recorded_stream.py -q
```

Use `uv run pytest --cov=coinbase_insights --cov-branch` for explicit coverage review if coverage options are not already configured in `pyproject.toml`.

## 4. Milestone overview

| Milestone | Status | Outcome | Primary skill |
|---|---|---|---|
| 0 | Complete | Reproducible Python project and quality commands | `part1-packaging-delivery` |
| 1 | Complete | Exact domain records and valid in-memory order book | `order-book-development` |
| 2 | Complete | Typed Coinbase contracts and source-to-domain mapping | `coinbase-feed-development` |
| 3 | Complete | Bounded histories and exact required metrics | `market-metrics-development` |
| 4 | Complete | Naive and AutoReg forecasts with correct maturity/error tracking | `forecasting-development` |
| 5 | Complete | Stable configuration, result contract, console, and NDJSON | `cli-output-development` |
| 6 | Pending | Resilient live WebSocket adapter and feed-health state machine | `coinbase-feed-development` |
| 7 | Pending | Five-second runtime composition and recorded-stream end-to-end path | `market-metrics-development` |
| 8 | Pending | Live hardening and resilience evidence | Feed, testing, and CLI skills |
| 9 | Pending | Docker, CI, reviewer documentation, and release gate | `part1-packaging-delivery` |

Testing is part of every milestone. Use `part1-testing` whenever choosing test boundaries, fixtures, fake-time behavior, properties, or coverage.

## 5. Milestone 0: Project foundation

### Goal

Create the smallest reproducible Python project that can import the package and run one test, format check, lint check, and type check.

### Files introduced

```text
pyproject.toml
uv.lock
.python-version
.gitignore
.env.example
src/coinbase_insights/__init__.py
tests/unit/test_package.py
```

Do not add all future package directories in this milestone.

### Configuration decisions

- Python 3.13.
- `src` package layout.
- `uv` for dependency resolution and locking.
- Runtime dependencies, added when first needed:
  - `websockets`;
  - Pydantic;
  - `sortedcontainers`;
  - `statsmodels`;
  - Typer;
  - Rich.
- Development dependencies:
  - pytest;
  - `pytest-asyncio`;
  - Hypothesis;
  - `pytest-cov`;
  - Ruff;
  - Pyright.

Pin a compatible resolved set in `uv.lock`; do not manually hard-code every transitive dependency.

Configure in `pyproject.toml`:

- package metadata and console entry point reserved for `coinbase-insights` once `cli.py` exists;
- Ruff formatting and linting;
- Pyright with a strict but practical project policy;
- pytest test paths, strict asyncio mode, markers, and branch coverage defaults;
- coverage source restricted to `coinbase_insights`.

### Focused validation

```bash
uv sync --all-groups
uv lock --check
uv run python -c "import coinbase_insights"
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q
```

### Exit criteria

- A clean environment installs from the lock file.
- The package imports from the `src` layout.
- All quality commands exist and pass.
- No secrets, virtual environments, caches, or generated reports are tracked.

## 6. Milestone 1: Domain records and order book

### Goal

Prove the hardest stateful rule independently of networking: snapshots and absolute updates produce the correct current book and immutable BBO.

### Files introduced

```text
src/coinbase_insights/domain/__init__.py
src/coinbase_insights/domain/events.py
src/coinbase_insights/domain/models.py
src/coinbase_insights/domain/order_book.py
tests/unit/domain/test_order_book.py
```

### Domain types

Define small frozen dataclasses or enums for:

- `Side` with `BID` and `ASK`;
- `PriceLevel` or equivalent `(price, quantity)` value;
- `BookSnapshot` containing complete bid and ask assignments;
- `PriceLevelUpdate` containing side, price, quantity, and event timestamp;
- immutable `BestBidAsk` with prices, quantities, and observation/source metadata;
- explicit invalid/unavailable state rather than zero-valued market data.

Implement `OrderBook` with two `SortedDict[Decimal, Decimal]` collections.

Required transitions:

- snapshot atomically replaces both sides;
- positive quantity inserts or replaces a level;
- zero quantity removes a level and tolerates removal of an absent level;
- invalidation clears usability immediately;
- only a new snapshot restores usability;
- best bid is maximum bid and best ask is minimum ask;
- one-sided, empty, non-positive, or crossed books have no valid BBO.

### Tests written first

- snapshot creates a valid BBO with associated quantities;
- second snapshot removes all levels from the first;
- absolute update replaces rather than adds quantity;
- zero update deletes a level;
- best level changes after insert/delete;
- decimal prices that would collide under float remain distinct;
- empty, one-sided, and crossed books are invalid;
- invalidation suppresses BBO until another snapshot;
- randomized update sequences agree with a slow dictionary reference model.

### Focused validation

```bash
uv run pytest tests/unit/domain/test_order_book.py -q
uv run pyright src/coinbase_insights/domain tests/unit/domain
```

### Exit criteria

- Domain tests include example and Hypothesis coverage.
- Domain modules contain no asyncio, WebSocket, Pydantic, CLI, output, or forecasting imports.
- Prices and quantities never pass through `float`.

## 7. Milestone 2: Coinbase message contracts and mapping

### Goal

Validate untrusted Coinbase JSON and map it into the already-tested domain without leaking source vocabulary into domain code.

### Files introduced

```text
src/coinbase_insights/coinbase/__init__.py
src/coinbase_insights/coinbase/messages.py
src/coinbase_insights/coinbase/mapper.py
tests/fixtures/coinbase/heartbeat.json
tests/fixtures/coinbase/level2_snapshot.json
tests/fixtures/coinbase/level2_updates.jsonl
tests/unit/coinbase/test_messages.py
tests/unit/coinbase/test_mapper.py
tests/contract/test_coinbase_fixtures.py
```

### Contract work

- Model the envelope fields `channel`, `timestamp`, `sequence_num`, and `events` with Pydantic.
- Model heartbeat and Level 2 event variants explicitly.
- Preserve numeric source fields as strings at the source contract, then convert to `Decimal` in the mapper.
- Allow unknown extra fields for compatible source evolution.
- Reject absent semantic fields, invalid timestamps, negative quantities, non-positive prices, unknown sides, and impossible event variants.
- Normalize Coinbase `offer` to domain `Side.ASK` in `mapper.py`.
- Preserve event-engine time, server-send time, sequence, product, and local receive time with distinct names.

Initial fixtures may be minimal payloads derived from the published AsyncAPI schema, but they must be labeled synthetic in test provenance. During live verification, add or replace them with sanitized messages actually observed from Coinbase and record that provenance in `docs/testing.md`.

### Test cases

- known snapshot, update, and heartbeat payloads validate;
- additional unknown fields do not break parsing;
- missing required semantic fields fail clearly;
- decimal strings map exactly;
- `offer` maps to `ASK` and `bid` maps to `BID`;
- zero quantity remains a valid delete instruction;
- negative quantity and invalid price fail;
- event and envelope timestamps remain distinct.

### Focused validation

```bash
uv run pytest tests/unit/coinbase tests/contract -q
uv run pytest tests/unit/domain tests/unit/coinbase tests/contract -q
```

### Exit criteria

- Every accepted fixture maps to typed domain events.
- Invalid source input cannot partially mutate the order book.
- Coinbase names and Pydantic models remain inside the adapter package.

## 8. Milestone 3: Histories and required metrics

### Goal

Calculate exact process-lifetime and rolling metrics over deterministic timestamped observations with bounded memory.

### Files introduced

```text
src/coinbase_insights/analytics/__init__.py
src/coinbase_insights/analytics/metrics.py
src/coinbase_insights/runtime/__init__.py
src/coinbase_insights/runtime/history.py
tests/unit/analytics/test_metrics.py
tests/unit/runtime/test_history.py
```

### Implementation

- Define immutable five-second `MidPriceObservation` records.
- Calculate spread and mid-price with `Decimal`.
- Track maximum spread from every valid BBO change, independently of sampled history.
- Implement bounded timestamped deques for observations and matured errors.
- Prune values outside the largest supported horizon.
- Calculate averages for 1, 5, and 15 minutes using $(t-W, t]$ semantics.
- Return both average and sample count; return unavailable when the count is zero.
- Do not insert stale or invalid observations into numeric histories.

### Boundary tests

- exact lower-bound timestamp is excluded and exact current timestamp is included;
- startup partial windows expose reduced counts;
- no observations return unavailable, not zero;
- transient BBO spread updates the process maximum between sample boundaries;
- old entries are pruned while required entries remain;
- memory remains bounded after a long generated sequence;
- all calculations retain expected decimal precision.

### Focused validation

```bash
uv run pytest tests/unit/analytics/test_metrics.py tests/unit/runtime/test_history.py -q
```

### Exit criteria

- All challenge metrics except forecasting are available from deterministic in-memory inputs.
- Window behavior is explicit at every boundary.
- Histories remain bounded for indefinite process operation.

## 9. Milestone 4: Forecasting and prediction ledger

### Goal

Produce a 60-second forecast without compromising feed processing, and measure primary and naive errors only when predictions mature correctly.

### Files introduced

```text
src/coinbase_insights/analytics/forecasting.py
tests/unit/analytics/test_forecasting.py
```

Extend domain records and runtime history only where the forecast contract requires it.

### First slice: naive baseline

- Forecast the latest valid mid-price at `predicted_at + 60 seconds`.
- Store `predicted_at`, `target_at`, model identity, predicted value, and status.
- Mature a prediction only against a valid observation on its exact target boundary.
- Calculate absolute error and append it to bounded 1/5/15-minute error histories.
- Mark a missing target observation unscored and never pair it with a later sample.

### Second slice: AutoReg adapter

- Accept up to 180 regular valid observations.
- Require at least 60 contiguous observations.
- Calculate first differences.
- Fit `statsmodels.tsa.ar_model.AutoReg` with 12 lags.
- Recursively forecast 12 five-second differences and add their sum to the latest mid-price.
- Return through a small typed forecasting interface.
- Run fitting outside the event-loop thread when integrated.
- Fall back to naive on insufficient history, gaps, singular/non-finite results, timeout, or model exception.

### Tests

- naive value and exact target timestamp;
- warm-up before 60 observations;
- deterministic synthetic trend produces a finite primary forecast;
- no future observation enters model training;
- exact target matures once;
- missing target is unscored;
- primary and naive MAE remain separate;
- fit exception, timeout, singular input, and non-finite result select fallback;
- prediction/error histories are bounded.

Mock the model boundary for failure tests; do not assert unstable internal coefficients from `statsmodels`.

### Focused validation

```bash
uv run pytest tests/unit/analytics/test_forecasting.py tests/unit/runtime/test_history.py -q
```

### Exit criteria

- A naive forecast is always available for a valid observation.
- Primary forecast failure is represented as fallback status, not a process failure.
- Forecast scoring has no target shift or future leakage.

## 10. Milestone 5: Configuration and output contracts

### Goal

Expose stable user inputs and result outputs before adding live networking, so the complete presentation path can be tested offline.

### Files introduced

```text
src/coinbase_insights/config.py
src/coinbase_insights/output/__init__.py
src/coinbase_insights/output/console.py
src/coinbase_insights/output/ndjson.py
tests/unit/output/test_ndjson.py
```

Add `cli.py` only when there is a runnable composition target, either late in this milestone or in Milestone 7.

### Configuration

Define typed settings with documented defaults:

- product ID, normalized to uppercase and conservatively validated;
- output mode: console or NDJSON;
- optional JWT environment-variable input;
- log level;
- five-second sample interval and 60-second horizon as fixed production defaults;
- heartbeat timeout, initial snapshot timeout, reconnect cap, and forecast fit timeout;
- forecast history and lag settings.

Keep challenge-defining intervals guarded from accidental incompatible combinations, such as a horizon not divisible by the sample interval.

### Result and rendering contract

- One immutable result record contains feed status, freshness, BBO, current/max spread, rolling averages/counts, forecasts, and rolling primary/naive errors.
- NDJSON emits exactly one JSON object per line to `stdout`.
- Decimal values serialize as strings; UTC timestamps use RFC 3339.
- Unavailable values serialize as `null` with an explicit status/reason.
- Rich console output uses the same record and never recalculates metrics.
- Diagnostics go to `stderr`.

### Tests

- product normalization and invalid product rejection;
- optional JWT is not represented in settings/log output;
- NDJSON schema, decimal strings, UTC timestamps, and one-line framing;
- unavailable/startup/fallback statuses;
- renderer does not mutate or recalculate the result.

### Focused validation

```bash
uv run pytest tests/unit/output -q
uv run pytest tests/unit/analytics tests/unit/output -q
```

### Exit criteria

- A synthetic result renders consistently in both modes.
- Machine-readable output can be piped without log contamination.
- No credential can appear through ordinary configuration representation.

## 11. Milestone 6: Live Coinbase client and health state machine

### Goal

Consume Coinbase safely, preserve sequence continuity, and expose explicit feed health without coupling the client to analytics or rendering.

### Files introduced

```text
src/coinbase_insights/coinbase/client.py
```

Add focused client tests under `tests/unit/coinbase/` using a scripted fake WebSocket transport.

### Connection behavior

- Connect to the public Advanced Trade WebSocket.
- Send `level2` subscription for the selected product and `heartbeats` subscription immediately.
- Include JWT only when configured.
- Assign a new local connection ID for every connection attempt.
- Track the per-connection `sequence_num` across all envelopes.
- Track heartbeat age using monotonic time.
- Yield complete mapped event batches to the runtime; never expose half-parsed messages.

### Recovery behavior

- First accepted sequence initializes sequence tracking.
- The next envelope must have the expected sequence; gap or regression invalidates continuity.
- Disconnect, parse/semantic failure, heartbeat timeout, or sequence failure emits an unhealthy state before reconnecting.
- Reconnect with injectable capped exponential backoff and jitter.
- A new connection starts with an unusable book.
- Only a fresh snapshot for the selected product marks order-book state usable.
- Startup snapshot timeout produces clear status and eventually a configured terminal startup error rather than retrying invisibly forever.

Use dependency injection or a narrow transport factory for tests; do not build a general networking framework.

### Tests

- exact subscription messages with and without optional JWT;
- heartbeat and Level 2 envelopes share sequence validation;
- normal contiguous stream maps and yields events;
- gap, regression, closure, timeout, and malformed semantic payload emit invalidation before reconnect;
- backoff progression, cap, and jitter boundaries without real sleep;
- fresh connection cannot reuse old valid state;
- new snapshot restores health.

### Focused validation

```bash
uv run pytest tests/unit/coinbase -q
uv run pytest tests/unit/domain tests/unit/coinbase -q
```

### Exit criteria

- No unit test opens the internet.
- Every continuity failure has deterministic state and recovery evidence.
- The client contains no metric, forecast, or presentation logic.

## 12. Milestone 7: Runtime sampler and application composition

### Goal

Compose the tested components into a deterministic offline end-to-end application, then connect the same runtime to the live adapter.

### Files introduced

```text
src/coinbase_insights/runtime/sampler.py
src/coinbase_insights/cli.py
src/coinbase_insights/__main__.py
tests/unit/runtime/test_sampler.py
tests/integration/test_cli.py
tests/integration/test_recorded_stream.py
```

### Runtime responsibilities

- Run the feed reader and sampler as coordinated asyncio tasks.
- Apply a complete mapped event synchronously with no `await` during book mutation.
- Observe every valid BBO change for maximum spread.
- Calculate the next UTC five-second boundary instead of repeatedly sleeping five seconds.
- At each boundary:
  1. obtain one immutable BBO/health snapshot;
  2. create a valid observation or explicit unavailable state;
  3. mature due predictions;
  4. append/prune histories;
  5. calculate rolling metrics and errors;
  6. generate naive and primary forecasts;
  7. build one immutable output record;
  8. render exactly once.
- Run model fitting with `asyncio.to_thread` and a timeout.
- On feed invalidation, invalidate the book immediately but continue status output every five seconds.
- On `SIGINT`/`SIGTERM`, stop intake, cancel coordinated tasks, close the socket, flush output, and exit cleanly.

### CLI responsibilities

- Expose `coinbase-insights --product BTC-USD` and `python -m coinbase_insights`.
- Support console and NDJSON modes.
- Configure logging without contaminating `stdout`.
- Validate startup configuration before opening the socket.
- Return meaningful exit codes for configuration, startup, and unexpected runtime failures.

### Deterministic integration tests

Drive a recorded stream through parser, mapper, order book, sampler, metrics, forecasting adapter, and NDJSON renderer with a fake clock.

Prove:

- no numeric output before snapshot;
- expected BBO and quantities after snapshot/update/delete;
- output occurs on exact five-second boundaries without drift;
- transient maximum spread is retained;
- 1/5/15-minute counts and averages are correct as history warms;
- 60-second forecasts mature at exact targets;
- a simulated gap produces unhealthy status and no stale metrics;
- a later snapshot restores output without carrying the old book;
- CLI streams are separated and shutdown is clean.

### Focused validation

```bash
uv run pytest tests/unit/runtime tests/integration -q
uv run python -m coinbase_insights --help
```

### Exit criteria

- Recorded input produces deterministic end-to-end NDJSON.
- The runtime remains alive and explicit during recoverable feed/model failures.
- Both supported entry points work.

## 13. Milestone 8: Live verification and resilience hardening

### Goal

Verify the deterministic design against the real public feed without making live behavior part of required CI.

### Live checks

- Run unauthenticated against `BTC-USD`; optional JWT is a separate smoke check only if credentials are available.
- Confirm receipt of heartbeat and Level 2 snapshot/update messages.
- Capture sanitized representative envelopes for deterministic contract fixtures and document capture date/provenance.
- Run long enough to observe:
  - immediate BBO and spread after snapshot;
  - 1-minute average warm-up;
  - first matured 60-second forecast error;
  - continued five-second output during a quiet period.
- Interrupt connectivity or inject a transport failure and confirm stale metrics are suppressed until a fresh snapshot.
- Send SIGINT and SIGTERM and confirm clean shutdown.

### Measurement

- Record observed message burst rate and maximum book depth for context.
- Measure update processing and forecast fit durations.
- Confirm AutoReg fitting finishes within its timeout on the target machine.
- Confirm memory remains stable during an extended run because histories are bounded.

Do not optimize based on hypothetical scale. Address only measured blocking, memory, or latency problems.

### Validation

After any live-discovered fix, first encode the case in a deterministic fixture/test, then rerun:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

### Exit criteria

- Unauthenticated live operation is demonstrated.
- Real payloads satisfy or deliberately update source contracts.
- Connection loss cannot result in stale current metrics.
- Live observations and limitations are documented without credentials or sensitive output.

## 14. Milestone 9: Packaging, CI, and submission documentation

### Goal

Make the completed PoC reproducible and reviewable from a clean checkout.

### Files introduced or completed

```text
Dockerfile
.dockerignore
.github/workflows/ci.yml
README.md
docs/architecture.md
docs/testing.md
```

Add a license only if the repository owner deliberately selects one.

### Docker

- Use a pinned small official Python base compatible with Python 3.13.
- Install from `uv.lock` without development dependencies.
- Run as a non-root user.
- Use an exec-form entrypoint.
- Keep credentials and local `.env` files out of build context and layers.
- Pass product/output settings at runtime.
- Confirm signals reach the Python process.

Required checks:

```bash
docker build -t coinbase-insights:local .
docker run --rm coinbase-insights:local --help
```

Perform a short live container smoke test separately from automated CI.

### CI

GitHub Actions must run, in order or parallel where independent:

1. `uv lock --check`;
2. Ruff format check;
3. Ruff lint;
4. Pyright;
5. pytest with branch coverage;
6. Docker build.

Required CI has no live Coinbase dependency. Use minimal permissions, concurrency cancellation, lock-keyed caching, and securely pinned third-party actions.

### README

Include:

- challenge summary and implemented scope;
- architecture summary and diagram/link;
- prerequisites and verified `uv` setup;
- unauthenticated local run command;
- optional JWT configuration without secret examples;
- console and NDJSON examples;
- test, lint, type-check, coverage, and Docker commands;
- assumptions and known limitations;
- feed gap/staleness behavior;
- forecast method, naive baseline, and interpretation limits;
- required “Working with AI” section based on the actual development history.

### Reviewer documentation

- `docs/architecture.md` presents the accepted implemented design, not future Part 2 infrastructure.
- `docs/testing.md` explains unit/contract/integration boundaries, fixture provenance, fake time, property testing, coverage interpretation, and optional live checks.
- Commands in documentation must be rerun exactly before submission.

### Exit criteria

- A clean checkout passes documented setup and all quality commands.
- The Docker image builds and displays CLI help.
- CI is green and contains no external-market dependency.
- Reviewer-facing documentation distinguishes implemented behavior, assumptions, and limitations.

## 15. Final acceptance matrix

| Challenge requirement | Implementation evidence | Test evidence |
|---|---|---|
| User selects product | Typer `--product` configuration | CLI validation/integration test |
| Output every five seconds | UTC-aligned runtime sampler | Fake-clock no-drift test |
| Highest bid/quantity | `OrderBook` immutable BBO | Snapshot/update/delete tests |
| Lowest ask/quantity | `OrderBook` immutable BBO | Snapshot/update/delete tests |
| Largest spread so far | Every-BBO-change maximum tracker | Between-boundary transient spread test |
| Average mid-price 1/5/15m | Bounded observation history and window metrics | Exact boundary and warm-up count tests |
| Forecast mid-price in 60s | Naive plus AutoReg 12-step forecast | Warm-up, finite forecast, fallback tests |
| Average forecast error 1/5/15m | Exact-target prediction ledger and error history | Maturity, missing-target, leakage tests |
| Correct recovery | Sequence/heartbeat health and snapshot gating | Gap, reconnect, stale suppression tests |
| Reviewer can run it | `uv`, README, Docker | CI and clean-environment smoke checks |

## 16. Final definition of done

Part 1 is complete only when all of the following are true:

- Every acceptance-matrix row has implementation and automated test evidence.
- A public unauthenticated Coinbase run emits valid metrics.
- Invalid or stale books never appear as current values.
- Primary forecast errors and naive baseline errors are both visible and correctly matured.
- Focused tests, full pytest, Ruff formatting/linting, Pyright, and Docker build pass.
- Branch coverage is reviewed, with domain and analytics failure paths strongly covered; the percentage is not achieved through low-value tests.
- Memory is bounded and model fitting does not block WebSocket consumption.
- SIGINT and SIGTERM shut down cleanly.
- No credentials, generated secrets, local paths, or sensitive logs are committed.
- README setup and run commands have been verified from a clean environment.
- The “Working with AI” section truthfully records delegated work, human rewrites/review, one caught agent mistake, and areas requiring supervision.
- Part 2 services and architecture remain outside the implementation.

## 17. Deferred decisions

Do not decide these during Part 1 unless live evidence forces a change:

- Azure deployment target;
- Snowflake ingestion or warehouse model;
- durable event retention;
- multi-product horizontal scaling;
- web API or graphical UI;
- cross-process persistence;
- production SLOs and multi-region recovery.

Record any such idea for the later Part 2 plan instead of expanding this implementation.