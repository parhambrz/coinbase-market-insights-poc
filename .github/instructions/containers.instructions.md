---
name: "Container Rules"
description: "Use when creating or changing the Part 1 Dockerfile, Docker build context, ignore rules, entrypoint, runtime user, or container smoke checks."
applyTo: ["Dockerfile", ".dockerignore"]
---

# Container Rules

- Build from a small pinned official Python image compatible with the project Python version.
- Install exactly from the committed lock file and exclude development dependencies from the runtime image.
- Use a multi-stage build only when it produces a materially smaller or safer runtime image.
- Run as a non-root user with a read-only-friendly application layout.
- Use an exec-form entrypoint so signals reach the Python process.
- Accept product, output mode, and optional settings as runtime arguments or environment variables; bake in no credentials.
- Keep build context small and exclude Git metadata, caches, virtual environments, coverage output, tests when unnecessary, and local secrets.
- Part 1 is one process; do not add Docker Compose without an explicitly approved second service.
- Validate image build, CLI help, and graceful termination after container changes.