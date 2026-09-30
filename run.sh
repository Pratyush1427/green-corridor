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

echo ""
echo "  Ambulance map:        http://127.0.0.1:${PORT:-8000}"
echo "  Traffic control room: http://127.0.0.1:${PORT:-8000}/police"
echo "  Press Ctrl+C to stop."
echo ""
exec uvicorn app:app --port "${PORT:-8000}"
