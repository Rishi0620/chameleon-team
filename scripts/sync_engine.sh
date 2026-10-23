#!/bin/sh
# Copy the proto engine into engine/chameleon/ (what the Docker image ships). Run from the repo root.
set -e
SRC=design/debate/proto
DST=engine/chameleon
mkdir -p "$DST"
for f in engine decompile search textfit contract finisher rules critic overlay; do
  sed 's/parents\[3\]/parents[2]/' "$SRC/$f.py" > "$DST/$f.py"
done
cat > "$DST/__init__.py" <<'PY'
"""Shipped copy of design/debate/proto (see scripts/sync_engine.sh). Do not edit here."""
from .engine import resize, resize_with_info  # noqa: F401
PY
