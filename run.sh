#!/usr/bin/env bash
# One-command start: creates the virtual environment on first run, installs packages,
# then starts the server at http://127.0.0.1:8000
set -e
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "Creating virtual environment (first run only)..."
  python3 -m venv venv
fi
source venv/bin/activate
pip install --quiet --disable-pip-version-check -r requirements.txt

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"   # HOST=0.0.0.0 lets phones on the same Wi-Fi connect (no login yet: trusted networks only)
ADDR="127.0.0.1"
if [ "$HOST" = "0.0.0.0" ]; then
  ADDR="$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
fi

echo ""
echo "  Organisation:  http://${ADDR}:${PORT}"
echo "  Ambulance:     http://${ADDR}:${PORT}/driver"
echo "  Junction:      http://${ADDR}:${PORT}/junction"
echo "  Control room:  http://${ADDR}:${PORT}/police"
echo "  Press Ctrl+C to stop."
echo ""
exec uvicorn app:app --host "$HOST" --port "$PORT"
