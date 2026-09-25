---
name: "Part 1 CI Rules"
description: "Use when creating or changing GitHub Actions workflows for dependency locking, formatting, linting, typing, pytest coverage, or Docker builds."
applyTo: [".github/workflows/*.yml", ".github/workflows/*.yaml"]
---

# Part 1 CI Rules

- Grant the minimum workflow permissions and pin third-party actions to immutable commit SHAs where practical.
- Use dependency caching keyed by the lock file without caching local secrets or mutable build output.
- Required CI must run lock consistency, formatter check, lint, type check, pytest with branch coverage, and Docker build once present.
- Keep required tests network-free. A live Coinbase check may be manual or scheduled and non-blocking.
- Upload useful coverage/test artifacts on failure or for review, with short retention.
- Avoid duplicated environments unless the project deliberately supports multiple Python versions.
- Use concurrency cancellation for superseded pull-request runs.
- Keep commands identical to documented local commands.
- Never expose secrets to pull requests from forks or print secret-bearing environment variables.