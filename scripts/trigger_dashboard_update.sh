#!/usr/bin/env bash
set -euo pipefail

TOKEN="${GITHUB_WORKFLOW_TOKEN:-}"
OWNER_REPO="${OWNER_REPO:-tamagomagomago/invest-dashboard}"
WORKFLOW_FILE="${WORKFLOW_FILE:-update-dashboard.yml}"
REF="${REF:-main}"
FORCE="${FORCE:-false}"

if [ -z "$TOKEN" ]; then
  echo "GITHUB_WORKFLOW_TOKEN is required." >&2
  exit 1
fi

status="$(
  if [ "$FORCE" = "true" ]; then
    body="{\"ref\":\"${REF}\",\"inputs\":{\"force\":\"true\"}}"
  else
    body="{\"ref\":\"${REF}\"}"
  fi

  curl -sS -o /tmp/invest_dashboard_dispatch_response.txt -w "%{http_code}" \
    -X POST \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -H "Content-Type: application/json" \
    "https://api.github.com/repos/${OWNER_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches" \
    -d "$body"
)"

if [ "$status" != "204" ]; then
  echo "Failed to dispatch workflow. HTTP status: $status" >&2
  cat /tmp/invest_dashboard_dispatch_response.txt >&2
  exit 1
fi

echo "Workflow dispatched: ${OWNER_REPO}/${WORKFLOW_FILE} @ ${REF}"
