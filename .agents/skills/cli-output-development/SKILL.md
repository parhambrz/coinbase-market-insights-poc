---
name: cli-output-development
description: "Develop or review the Part 1 command-line interface and output adapters. Use for Typer options, configuration validation, process lifecycle, exit codes, Rich console tables, NDJSON schema, Decimal serialization, status records, logging separation, or graceful shutdown."
argument-hint: "Describe the CLI, configuration, or output change"
user-invocable: true
disable-model-invocation: false
---

# CLI and Output Development

## Ownership

Work in `cli.py`, `config.py`, `__main__.py`, `output/`, and their tests. The CLI is the composition root; renderers consume immutable result records.

## Interface rules

- Require or default one startup product and normalize it to uppercase.
- Keep public feed operation possible without credentials; optional JWT comes from environment/configuration, never a CLI echo or log.
- Send metric records to `stdout` and diagnostics to `stderr`.
- Support a readable Rich console view and stable one-record-per-line NDJSON.
- Serialize decimal values as strings and timestamps as UTC RFC 3339 values.
- Emit explicit startup/recovery statuses such as `connecting`, `awaiting_snapshot`, `feed_stale`, `warming_up`, and `fallback`.
- Handle `SIGINT` and `SIGTERM` by closing the socket, cancelling tasks, flushing output, and returning a meaningful exit code.

## Workflow

1. Define the externally visible option or result-record change.
2. Keep formatting out of domain and analytics objects.
3. Add CLI runner or renderer tests that assert behavior, streams, and exit codes.
4. Run focused tests, then a local `--help` and recorded-input smoke check.
5. Update README examples when the public interface changes.

## Review checks

- NDJSON remains parseable and contains no log lines.
- Unavailable values are `null` with status/reason, never misleading zeros.
- Console formatting does not alter numeric values.