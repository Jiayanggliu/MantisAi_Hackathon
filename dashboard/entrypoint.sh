#!/bin/sh
# Build out/ from data/prepped/ if it isn't there yet, then serve.
# Keeps `docker compose up` to one command without committing derived data.
set -e

if [ ! -f /app/out/analysis.json ] || [ ! -f /app/out/jobs_bucketed.parquet ]; then
  if [ ! -f /app/data/prepped/jobs.parquet ]; then
    echo "FATAL: data/prepped/jobs.parquet is missing." >&2
    echo "Generate the data first -- see data/README.md, steps 1 to 4." >&2
    exit 1
  fi
  echo "out/ is empty; running analysis.py ..."
  cd /app && python analysis.py
  echo "analysis.py done."
fi

# Traces are a bonus view; never let them stop the dashboard coming up.
if [ ! -f /app/out/trace.json.gz ]; then
  echo "building Perfetto traces ..."
  ( cd /app && python scripts/make_trace.py \
      && python scripts/make_trace.py --waste-only \
      && python scripts/make_trace.py --focus r216287-n200569 ) \
    || echo "WARN: trace build failed; the dashboard runs without it." >&2
fi

exec streamlit run /app/dashboard/app.py \
  --server.port=3000 --server.address=0.0.0.0 \
  --server.headless=true --browser.gatherUsageStats=false
