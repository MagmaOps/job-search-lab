#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-api}"

# Wait for the database, then ensure schema + seed exist (idempotent).
python - <<'PY'
import time, sys
from sqlalchemy import text
from jobsearch.db import engine
for attempt in range(60):
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        break
    except Exception as e:
        print(f"waiting for db ({attempt+1}/60): {e}", flush=True)
        time.sleep(2)
else:
    print("database never became ready", file=sys.stderr)
    sys.exit(1)
PY

python -m jobsearch.init_db

case "$ROLE" in
  api)
    exec uvicorn jobsearch.api:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    exec python -m jobsearch.worker
    ;;
  *)
    echo "unknown role: $ROLE (expected 'api' or 'worker')" >&2
    exit 1
    ;;
esac
