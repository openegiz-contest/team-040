#!/usr/bin/env bash
# Wait for the team's own MQTT -> Ditto -> proxy path, not only container health.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker compose -f "$ROOT/deploy/compose/docker-compose.yml" -f "$ROOT/team/compose.yml" \
  exec -T team-ui python -m team.gateway.readiness
