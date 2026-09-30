"""Downloads Bengaluru hospitals from OpenStreetMap into static/hospitals.json.

Run once (or whenever you want fresh data):  python fetch_hospitals.py
Data (c) OpenStreetMap contributors, ODbL.
"""
import json
from pathlib import Path

from osm import BBOX, overpass

QUERY = f'[out:json][timeout:90];nwr["amenity"="hospital"]({BBOX});out center tags;'
OUT_PATH = Path(__file__).parent / "static" / "hospitals.json"


def main() -> None:
    data = overpass(QUERY)

    hospitals = []
    for el in data["elements"]:
        tags = el.get("tags", {})
        # Nodes have lat/lon; ways/relations (building outlines) have a center point.
        point = el if "lat" in el else el.get("center")
        if not point or not tags.get("name"):
            continue
        hospitals.append({
            "name": tags["name"].strip('" '),
            "lat": round(point["lat"], 6),
            "lon": round(point["lon"], 6),
            "emergency": tags.get("emergency") == "yes",
            "phone": tags.get("phone") or tags.get("contact:phone"),
        })

    hospitals.sort(key=lambda h: h["name"])
    OUT_PATH.write_text(json.dumps(hospitals, indent=1, ensure_ascii=False))
    emergency = sum(h["emergency"] for h in hospitals)
    print(f"Saved {len(hospitals)} hospitals ({emergency} with emergency departments) to {OUT_PATH}")


if __name__ == "__main__":
    main()
