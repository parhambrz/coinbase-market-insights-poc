---
name: "Python Project Configuration"
description: "Use when changing pyproject.toml, uv dependency configuration, Python version files, lint, type-check, pytest, or coverage settings."
applyTo: ["pyproject.toml", ".python-version", "uv.lock"]
---

# Python Project Configuration

- Use `uv` and commit `uv.lock` for reproducible application and development dependencies.
- Change dependencies through `uv` commands; never hand-edit `uv.lock`.
- Separate runtime dependencies from development/test dependency groups.
- Pin the supported Python range intentionally and keep Docker/CI versions consistent with it.
- Keep formatter, linter, type-checker, pytest, and coverage configuration centralized in `pyproject.toml` where supported.
- Prefer Ruff for formatting/linting and a strict practical type-check configuration.
- Configure pytest markers explicitly, including any optional live test marker.
- Collect branch coverage for `src/coinbase_insights`; do not omit difficult domain branches to inflate results.
- Add a dependency only when its value exceeds its maintenance and supply-chain cost.