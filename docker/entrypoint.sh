#!/bin/sh
set -e

DATA_DIR="${MFDATA_DATA_DIR:-/data}"
DB="${MFDATA_DB:-$DATA_DIR/mfdata.db}"

if [ "${MFDATA_AUTO_SYNC:-1}" = "1" ] && [ ! -f "$DB" ]; then
  echo "No database found at $DB - running initial AMFI sync..."
  python -m pipeline sync --bootstrap-days "${MFDATA_BOOTSTRAP_DAYS:-365}" || {
    echo "WARNING: initial sync failed. The API will start without data."
    echo "Run 'docker compose exec api python -m pipeline sync' once AMFI is reachable."
  }
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
