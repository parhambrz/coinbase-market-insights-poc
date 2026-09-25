# Part 1 Expected Repository Structure

This is the intended end-state layout for the Part 1 submission. Create entries only when their implementation slice is needed; empty placeholder modules are not required.

```text
.
├── .agents/
│   ├── plans/
│   │   ├── part-1-poc-architecture.md
│   │   ├── part-1-implementation-plan.md
│   │   └── part-1-repository-structure.md
│   └── skills/
│       ├── coinbase-feed-development/SKILL.md
│       ├── order-book-development/SKILL.md
│       ├── market-metrics-development/SKILL.md
│       ├── forecasting-development/SKILL.md
│       ├── cli-output-development/SKILL.md
│       ├── part1-testing/SKILL.md
│       └── part1-packaging-delivery/SKILL.md
├── .github/
│   ├── copilot-instructions.md
│   ├── instructions/
│   │   ├── python-source.instructions.md
│   │   ├── tests.instructions.md
│   │   ├── project-config.instructions.md
│   │   ├── containers.instructions.md
│   │   ├── ci.instructions.md
│   │   └── documentation.instructions.md
│   └── workflows/
│       └── ci.yml
├── docs/
│   ├── architecture.md
│   └── testing.md
├── src/
│   └── coinbase_insights/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── coinbase/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── mapper.py
│       │   └── messages.py
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── events.py
│       │   ├── models.py
│       │   └── order_book.py
│       ├── analytics/
│       │   ├── __init__.py
│       │   ├── forecasting.py
│       │   └── metrics.py
│       ├── runtime/
│       │   ├── __init__.py
│       │   ├── history.py
│       │   └── sampler.py
│       └── output/
│           ├── __init__.py
│           ├── console.py
│           └── ndjson.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   └── coinbase/
│   │       ├── heartbeat.json
│   │       ├── level2_snapshot.json
│   │       └── level2_updates.jsonl
│   ├── unit/
│   │   ├── analytics/
│   │   │   ├── test_forecasting.py
│   │   │   └── test_metrics.py
│   │   ├── coinbase/
│   │   │   ├── test_mapper.py
│   │   │   └── test_messages.py
│   │   ├── domain/
│   │   │   └── test_order_book.py
│   │   ├── output/
│   │   │   └── test_ndjson.py
│   │   └── runtime/
│   │       ├── test_history.py
│   │       └── test_sampler.py
│   ├── contract/
│   │   └── test_coinbase_fixtures.py
│   └── integration/
│       ├── test_cli.py
│       └── test_recorded_stream.py
├── .dockerignore
├── .env.example
├── .gitignore
├── .python-version
├── Dockerfile
├── LICENSE                         # only if the author chooses a license
├── README.md
├── pyproject.toml
└── uv.lock
```

## Boundary ownership

- `coinbase/` owns external protocol parsing, mapping, connection continuity, and reconnect behavior.
- `domain/` owns immutable domain records and mutable order-book state; it imports no Coinbase, output, CLI, or forecasting adapters.
- `analytics/` owns pure metric and forecast calculations over domain observations.
- `runtime/` owns clocks, bounded histories, five-second orchestration, and coordination of domain/analytics operations.
- `output/` owns presentation only and consumes immutable result records.
- `cli.py` and `__main__.py` form the composition root and process lifecycle.

## Test organization

- `unit/` contains deterministic, network-free tests for one module or domain behavior.
- `contract/` validates captured Coinbase payloads against source-boundary contracts.
- `integration/` composes multiple internal components using recorded input; it remains network-free.
- Live Coinbase checks are manual smoke tests, not required CI tests.
- Fixture files preserve source payload shape and contain no credentials.

## Submission-facing files

- `README.md` is the entry point: setup, run, test, Docker, assumptions, limitations, sample output, and the required “Working with AI” section.
- `docs/architecture.md` is the polished submission version of the accepted architecture, not an implementation diary.
- `docs/testing.md` explains test categories, deterministic time/feed strategies, coverage interpretation, and optional live verification.
- `.agents/` and `.github/instructions/` are development aids; they do not replace reviewer-facing documentation.