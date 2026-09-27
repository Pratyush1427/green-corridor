"""Junction list and app settings."""
import os

from dotenv import load_dotenv

load_dotenv()

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")
DB_PATH = os.getenv("DB_PATH", "traffic.db")
POLL_MINUTES = 15

# Approximate coordinates: check each one on the map during setup and adjust.
JUNCTIONS = [
    {"id": "silk_board", "name": "Silk Board", "lat": 12.9177, "lon": 77.6238},
    {"id": "hebbal", "name": "Hebbal flyover", "lat": 13.0358, "lon": 77.5970},
    {"id": "kr_puram", "name": "KR Puram", "lat": 12.9967, "lon": 77.6690},
    {"id": "marathahalli", "name": "Marathahalli bridge", "lat": 12.9569, "lon": 77.7011},
    {"id": "majestic", "name": "Majestic", "lat": 12.9776, "lon": 77.5713},
    {"id": "richmond_circle", "name": "Richmond Circle", "lat": 12.9634, "lon": 77.5955},
]

JUNCTIONS_BY_ID = {j["id"]: j for j in JUNCTIONS}
