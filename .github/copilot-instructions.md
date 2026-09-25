# Part 1 Project Rules

- Scope work to the Coinbase challenge Part 1 unless the user explicitly requests Part 2.
- Treat [the Part 1 architecture](../.agents/plans/part-1-poc-architecture.md) as the behavioral source of truth and [the repository structure](../.agents/plans/part-1-repository-structure.md) as the ownership map.
- Preserve exact market values with `Decimal`; never use `float` for prices or quantities.
- Never emit stale or invalid order-book state as current data.
- Keep source adapters, domain state, analytics, runtime orchestration, and output rendering separated according to the ownership map.
- Prefer deterministic captured-feed tests and fake time over live-network tests.
- After each substantive change, run the narrowest relevant executable check, then broader checks when appropriate.
- Do not add Azure, Snowflake, dbt, Kafka, databases, web APIs, or distributed infrastructure to Part 1 without explicit approval.
- Do not commit credentials, Coinbase JWTs, generated secrets, or sensitive terminal output.
- Keep reviewer setup simple and document commands that were actually verified.