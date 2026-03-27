#!/bin/sh
set -eu

INTERVAL_SECONDS="${CRAWLER_INTERVAL_SECONDS:-1800}"
INITIAL_BACKFILL_DAYS="${CRAWLER_INITIAL_BACKFILL_DAYS:-30}"

echo "[crawler] bootstrap database and seed data..."
python -c "import scraper_job as s; s.recreate_db(); s.seed_historical_prices(); s.seed_historical_stocks(); s.run_scraper(backfill_days=${INITIAL_BACKFILL_DAYS})"

echo "[crawler] starting loop, interval=${INTERVAL_SECONDS}s"
while true; do
  sleep "${INTERVAL_SECONDS}"
  echo "[crawler] running periodic scrape..."
  python -c "import scraper_job as s; s.run_scraper(backfill_days=0)"
done
