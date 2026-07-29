#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

until docker compose exec postgres pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-findb}" >/dev/null 2>&1; do
  echo "waiting for postgres..."
  sleep 1
done

docker compose exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-findb}" < data/financial_data.sql
echo "loaded financial_data.sql"