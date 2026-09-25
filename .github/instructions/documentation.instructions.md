---
name: "Part 1 Documentation Rules"
description: "Use when changing README or reviewer-facing Markdown documentation for architecture, setup, testing, assumptions, output, limitations, or Working with AI."
applyTo: ["README.md", "docs/**/*.md"]
---

# Part 1 Documentation Rules

- Write for a reviewer starting from a clean checkout.
- Keep setup, local run, test, lint/type-check, and Docker commands executable and synchronized with project configuration.
- State feed assumptions, process-lifetime state, recovery behavior, forecast limitations, and optional authentication explicitly.
- Include representative output without claiming it is live or guaranteed.
- Keep architecture rationale in `docs/architecture.md` and testing strategy in `docs/testing.md`; link rather than duplicate long sections.
- The README must contain the challenge-required “Working with AI” section based on actual work: delegated work, rewritten work, one caught agent mistake, and unsupervised boundaries.
- Distinguish implemented behavior from proposed or future behavior.
- Do not include secrets, personal paths, machine-specific output, or unsupported performance claims.