"""Junction list and app settings."""
import os

from dotenv import load_dotenv

load_dotenv()

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")
DB_PATH = os.getenv("DB_PATH", "traffic.db")
POLL_MINUTES = 15

# Congestion hotspots. Coordinates marked "approx" are rough; check them on the map
# and adjust. The rest were looked up in OpenStreetMap.
# Budget: each junction costs 96 TomTom requests/day at a 15-minute interval
# (19 junctions = 1,824/day, under the free limit of 2,500/day).
JUNCTIONS = [
    {"id": "silk_board", "name": "Silk Board", "lat": 12.9177, "lon": 77.6238},
    {"id": "hebbal", "name": "Hebbal flyover", "lat": 13.0358, "lon": 77.5970},
    {"id": "kr_puram", "name": "KR Puram", "lat": 12.9967, "lon": 77.6690},
    {"id": "marathahalli", "name": "Marathahalli bridge", "lat": 12.9569, "lon": 77.7011},
    {"id": "majestic", "name": "Majestic", "lat": 12.9776, "lon": 77.5713},
    {"id": "richmond_circle", "name": "Richmond Circle", "lat": 12.9634, "lon": 77.5955},
    {"id": "iblur", "name": "Iblur junction", "lat": 12.9207, "lon": 77.6652},
    {"id": "ecospace", "name": "Ecospace, Bellandur ORR", "lat": 12.9283, "lon": 77.6812},
    {"id": "bommanahalli", "name": "Bommanahalli, Hosur Rd", "lat": 12.9131, "lon": 77.6251},
    {"id": "domlur", "name": "Domlur flyover", "lat": 12.9583, "lon": 77.6414},
    {"id": "trinity_circle", "name": "Trinity Circle", "lat": 12.9726, "lon": 77.6197},
    {"id": "mekhri_circle", "name": "Mekhri Circle", "lat": 13.0145, "lon": 77.5822},
    {"id": "anand_rao_circle", "name": "Anand Rao Circle", "lat": 12.9807, "lon": 77.5747},
    {"id": "town_hall", "name": "Town Hall", "lat": 12.9639, "lon": 77.5843},
    {"id": "sirsi_circle", "name": "Sirsi Circle, Mysore Rd", "lat": 12.9605, "lon": 77.5569},
    {"id": "sony_world", "name": "Sony World junction (approx)", "lat": 12.9366, "lon": 77.6269},
    {"id": "jayadeva", "name": "Jayadeva flyover (approx)", "lat": 12.9180, "lon": 77.5995},
    {"id": "hope_farm", "name": "Hope Farm, Whitefield (approx)", "lat": 12.9846, "lon": 77.7516},
    {"id": "yeshwanthpur", "name": "Yeshwanthpur circle (approx)", "lat": 13.0245, "lon": 77.5500},
]

JUNCTIONS_BY_ID = {j["id"]: j for j in JUNCTIONS}
