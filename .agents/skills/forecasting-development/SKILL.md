---
name: forecasting-development
description: "Develop, evaluate, test, or debug the Part 1 60-second mid-price forecast. Use for statsmodels AutoReg, first differences, lag selection, warm-up, naive persistence baseline, prediction ledger, exact target maturity, MAE, fallback, model timeout, or leakage prevention."
argument-hint: "Describe the forecasting or error-measurement task"
user-invocable: true
disable-model-invocation: false
---

# Forecasting Development

## Ownership

Work primarily in `analytics/forecasting.py`, domain forecast records, and focused analytics/runtime tests.

## Model contract

- Always produce or retain naive persistence as the baseline and fallback.
- The primary model is `statsmodels` AutoReg over first differences of regular five-second valid mid-prices.
- Default design: up to 180 recent observations, minimum 60 contiguous observations, 12 lags, and a 12-step forecast.
- Add predicted differences to the latest mid-price to recover the price-level forecast.
- Fit outside the asyncio event-loop thread and enforce a recoverable timeout.
- Record model name/version, prediction time, exact target time, forecast value, and status.
- Score only against the valid sample at the exact target boundary; otherwise mark unscored.
- Never use observations at or after the target when training its prediction.

## Workflow

1. Define the training cutoff and target timestamp before changing model code.
2. Add deterministic synthetic-series tests for warm-up, target alignment, and fallback.
3. Make model fitting an adapter behind a small typed interface.
4. Run the focused forecast test, then forecast-ledger and sampler tests.
5. Compare primary MAE with naive MAE; do not claim improvement without evidence.

## Review checks

- Non-finite values, singular fits, insufficient data, timeout, or model exceptions degrade to naive output.
- A model failure cannot stop feed ingestion or five-second output.
- Random train/test splits are never used for time-series evaluation.