#!/bin/sh
set -e
cd /app
# MuseTalk weights (about 5 GB) are downloaded once into the mounted volume
if [ ! -f third_party/MuseTalk/models/musetalkV15/unet.pth ] && [ "${SKIP_WEIGHTS:-0}" != "1" ]; then
  echo "First run: downloading MuseTalk weights..."
  .venv-musetalk/bin/python download_weights.py
fi
exec "$@"
