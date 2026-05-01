#!/usr/bin/env bash
set -euo pipefail

root="${1:-.}"
plan_path="${2:-$(mktemp /tmp/meminit-migration-plan.XXXXXX.json)}"

echo "Running meminit context (json) at root: ${root}" >&2
meminit context --root "${root}" --format json

echo "Generating migration plan: ${plan_path}" >&2
meminit scan --root "${root}" --plan "${plan_path}" --format json

echo "Running readiness checks" >&2
meminit doctor --root "${root}" --format json || true
meminit check --root "${root}" --format json || true

echo "Preview plan-driven fixes" >&2
meminit fix --root "${root}" --plan "${plan_path}" --dry-run --format json

echo "Next:" >&2
echo "  1) Review ${plan_path}" >&2
echo "  2) Apply config updates if needed" >&2
echo "  3) Run: meminit fix --root \"${root}\" --plan \"${plan_path}\" --no-dry-run --format json" >&2
echo "  4) Re-run: meminit check --root \"${root}\" --format json" >&2
