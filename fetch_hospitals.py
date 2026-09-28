"""Downloads Bengaluru hospitals from OpenStreetMap into static/hospitals.json.

Run once (or whenever you want fresh data):  python fetch_hospitals.py
Data (c) OpenStreetMap contributors, ODbL.
"""
import json
import time
from pathlib import Path

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
BBOX = "12.83,77.45,13.14,77.78"  # south, west, north, east around Bengaluru
QUERY = f'[out:json][timeout:90];nwr["amenity"="hospital"]({BBOX});out center tags;'
OUT_PATH = Path(__file__).parent / "static" / "hospitals.json"


def fetch(attempts: int = 3) -> dict:
    """The public Overpass server is often busy (504/429), so retry a few times."""
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.post(
                OVERPASS_URL,
                data={"data": QUERY},
                headers={"User-Agent": "green-corridor/0.1", "Accept": "application/json"},
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            if attempt == attempts:
                raise
            print(f"Attempt {attempt} failed ({e}), retrying in 20s...")
            time.sleep(20)


def main() -> None:
    data = fetch()

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
