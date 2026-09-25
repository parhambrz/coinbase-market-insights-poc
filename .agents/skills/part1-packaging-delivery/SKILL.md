---
name: part1-packaging-delivery
description: "Package and deliver Coinbase challenge Part 1. Use for uv and pyproject setup, dependency locking, Ruff or type checking, Dockerfile and .dockerignore, GitHub Actions CI, coverage publishing, README run commands, reproducible setup, or release-readiness checks."
argument-hint: "Describe the packaging, Docker, CI, or delivery task"
user-invocable: true
disable-model-invocation: false
---

# Part 1 Packaging and Delivery

## Ownership

Use this workflow for `pyproject.toml`, `uv.lock`, `.python-version`, Docker files, `.github/workflows/`, and reviewer setup commands. Follow the corresponding file-scoped instructions.

## Workflow

1. Verify the current local install, test, lint, type-check, and run commands before documenting or automating them.
2. Change dependencies with `uv`; commit lock changes and verify lock consistency.
3. Keep runtime and development dependencies separate.
4. Build a non-root container from the lock file with an exec-form entrypoint.
5. Make CI call the same commands used locally: lock check, format, lint, type check, pytest branch coverage, then Docker build.
6. Keep live Coinbase checks outside required CI.
7. Run a clean-environment or container smoke test for `--help`, recorded input where available, and graceful termination.

## Delivery checks

- Clean checkout instructions are complete and minimal.
- Python versions agree across project config, CI, and Docker.
- No credentials, local paths, caches, virtual environments, or coverage artifacts enter the image or repository.
- Workflow permissions are minimal and external actions are securely pinned.
- README commands match verified behavior.
- The challenge-required “Working with AI” section describes actual use and review, not boilerplate.

Packaging follows core correctness. Do not spend submission time on deployment infrastructure while domain or time-series tests are weak.