#!/usr/bin/env bash
# Everything a fresh clone needs before `docker compose up` works.
#
#   ./scripts/bootstrap.sh
#
# Downloads the raw MIT release, builds data/prepped/, generates data/synthetic/,
# and verifies all five files against data/checksums.txt. Each step is skipped if
# its output is already there, so running it twice is harmless.
#
# data/ is never committed: the source is CC BY-NC-ND and docs/submission.md asks
# us not to. Everyone generates it locally and the checksums prove we all got the
# same bytes.
set -euo pipefail

cd "$(dirname "$0")/.."
RAW_URL="https://mantisgrid-hackathon.s3.us-east-1.amazonaws.com/track-2-raw.zip"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is not available. Install Docker Desktop and start it." >&2
  echo "On a Mac the CLI may be at /Applications/Docker.app/Contents/Resources/bin" >&2
  exit 1
fi

# 1. raw --------------------------------------------------------------------
if [ -f data/raw/scheduler_data.csv ] && [ -f data/raw/dcgm.csv ]; then
  step "1/4 raw data already present, skipping download"
else
  step "1/4 downloading the raw MIT SuperCloud release (9.3 MB)"
  mkdir -p data/raw
  curl -fSL --retry 3 -o track-2-raw.zip "$RAW_URL"
  unzip -o -q track-2-raw.zip -d data/raw
  echo "unpacked into data/raw/"
fi

# 2. prepped ----------------------------------------------------------------
if [ -f data/prepped/jobs.parquet ] && [ -f data/prepped/gpus.parquet ]; then
  step "2/4 data/prepped already present, skipping prep"
else
  step "2/4 building data/prepped/ (scripts/prep_data.py, in the pinned image)"
  docker compose run --rm prep
fi

# 3. synthetic --------------------------------------------------------------
if [ -f data/synthetic/findings.json ]; then
  step "3/4 data/synthetic already present, skipping generate"
else
  step "3/4 generating data/synthetic/ (the findings the API serves)"
  # The shipped generator segfaults intermittently -- seen on arm64 under Docker
  # Desktop, part way through, on roughly half of cold runs. It is deterministic
  # when it does finish (findings.json is byte-identical every time and matches
  # data/checksums.txt), so a retry is safe and is all it needs.
  for attempt in 1 2 3 4 5; do
    if docker compose run --rm generate; then
      break
    fi
    if [ "$attempt" = 5 ]; then
      echo "generate failed 5 times. See data/README.md step 3." >&2
      exit 1
    fi
    echo "generate crashed (attempt $attempt); retrying ..." >&2
    rm -rf data/synthetic
    sleep 2
  done
fi

# 4. verify -----------------------------------------------------------------
step "4/4 checking all five files against data/checksums.txt"
docker compose run --rm prep python scripts/checksum_data.py

cat <<'EOF'

Ready. Bring it up with:

    docker compose up

  :3000  the dashboard        (builds out/ on first start; takes ~30s)
  :8000  the MantisGrid API   (/docs for the interactive spec)
  :8888  JupyterLab           (starter/notebook.ipynb)

EOF
