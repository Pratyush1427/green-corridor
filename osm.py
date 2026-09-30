"""Shared helper for downloading OpenStreetMap data through the Overpass API.

Data (c) OpenStreetMap contributors, ODbL.
"""
import math
import time

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
BBOX = "12.83,77.45,13.14,77.78"  # south, west, north, east around Bengaluru


def overpass(query: str, attempts: int = 3, timeout: float = 120) -> dict:
    """Run an Overpass query. The public server is often busy (504/429), so retry a few times."""
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": "green-corridor/0.1", "Accept": "application/json"},
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            if attempt == attempts:
                raise
            print(f"Attempt {attempt} failed ({e}), retrying in 20s...")
            time.sleep(20)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in metres (fine for short city distances)."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371000 * math.hypot(x, y)
