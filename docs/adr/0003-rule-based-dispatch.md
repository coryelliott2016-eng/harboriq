# ADR 0003 — Rule-based, explainable dispatch scoring

Status: Accepted

## Context
Shops want help choosing which technician to send. There is no historical
dataset to train a model on, and dispatchers need to understand and
override suggestions.

## Decision
`app/services/dispatch.py` ranks candidates with a deterministic weighted
score (urgency, revenue, customer value, travel distance, parts readiness,
technician fit, current workload) and returns the per-factor breakdown,
which the UI shows (`frontend/src/components/DispatchBreakdown.tsx`). A human
always makes the assignment.

## Consequences
- Suggestions are explainable and testable.
- This is **not** machine learning or generative AI. Public copy must say
  "rule-based" or "smart dispatch suggestions", not "AI-powered dispatch",
  unless and until a model is actually introduced.
