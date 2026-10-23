#!/usr/bin/env bash
# Lab 5 · run the integration tests on your laptop, the way CI runs them:
# a throwaway PostgreSQL, the API from source, then Jest. No Node.js needed.
# From the root of your fork:   bash lab05-ci-pipeline/itest.sh
# Your api/ folder is mounted read-only: nothing on your laptop changes.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
[ -f api/package.json ] || { echo "Run this from the root of your fork (api/package.json not found)"; exit 1; }

NET=lab5-itest
DB=lab5-itest-db
PW=test-only               # a throwaway database that lives for one minute

cleanup() {
  docker rm -fv "$DB" >/dev/null 2>&1 || true      # -v: also its anonymous data volume
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" \
  -e POSTGRES_USER=todo -e POSTGRES_DB=todo -e POSTGRES_PASSWORD="$PW" \
  --health-cmd "pg_isready -h localhost -U todo -d todo" \
  --health-interval 2s --health-timeout 3s --health-retries 15 \
  postgres:17-alpine >/dev/null

printf 'Waiting for PostgreSQL '
for _ in $(seq 60); do
  state=$(docker inspect -f '{{.State.Health.Status}}' "$DB")
  [ "$state" = healthy ] && break
  [ "$state" = unhealthy ] && { echo; docker logs "$DB"; exit 1; }
  printf '.'; sleep 1
done
echo " $state"
[ "$state" = healthy ] || { docker logs "$DB"; exit 1; }

docker run --rm --network "$NET" -v "$PWD/api:/src:ro" \
  -e DB_HOST="$DB" -e DB_PASSWORD="$PW" -e API_URL=http://localhost:5000 \
  node:24-alpine sh -c '
    cp -r /src /app && cd /app && rm -f .env
    npm ci --no-audit --no-fund --loglevel=error
    node server.js > /tmp/server.log 2>&1 &
    for i in $(seq 30); do
      wget -qO /dev/null http://localhost:5000/api/todos 2>/dev/null && break
      sleep 1
    done
    npx jest --ci --runInBand --testPathPatterns=integration && exit 0
    echo "----- API log -----"; cat /tmp/server.log; exit 1'
