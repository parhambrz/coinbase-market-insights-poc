---
name: "Python Source Rules"
description: "Use when creating or changing Python application source under src, including domain, Coinbase adapters, analytics, runtime, CLI, and output modules."
applyTo: "src/**/*.py"
---

# Python Source Rules

- Target the Python version declared in `pyproject.toml` and `.python-version`.
- Add complete type annotations to public functions, methods, and dataclass fields.
- Prefer immutable frozen dataclasses for records passed between layers; keep mutation inside explicit stateful objects such as `OrderBook`.
- Use timezone-aware UTC datetimes for labels and a monotonic clock for elapsed-time scheduling.
- Raise specific domain or adapter exceptions; catch errors only where recovery or user-facing status is decided.
- Keep I/O at adapters and orchestration boundaries. Domain and metric calculations should be deterministic and network-free.
- Do not block the asyncio event loop with model fitting or other CPU-heavy work.
- Use structured logging with lazy interpolation. Never log JWTs or full secret-bearing subscription data.
- Avoid speculative abstractions, one-letter names, and comments that merely restate code.
- Add or update focused tests with each behavioral change.