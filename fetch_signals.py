"""Downloads Bengaluru traffic signals from OpenStreetMap into static/signals.json.

Run once (or whenever you want fresh data):  python fetch_signals.py
Data (c) OpenStreetMap contributors, ODbL.

OpenStreetMap often maps one signal per approach road, so a single junction can have
several points a few metres apart. Points within MERGE_RADIUS_M are merged into one signal.
"""
import json
from pathlib import Path

from osm import BBOX, distance_m, overpass

QUERY = f'[out:json][timeout:90];node["highway"="traffic_signals"]({BBOX});out;'
OUT_PATH = Path(__file__).parent / "static" / "signals.json"
MERGE_RADIUS_M = 40


def merge_nearby(nodes: list) -> list:
    """Greedy clustering: each node joins the first cluster whose centre is close enough."""
    clusters = []
    for n in nodes:
        for c in clusters:
            if distance_m(n["lat"], n["lon"], c["lat"], c["lon"]) <= MERGE_RADIUS_M:
                c["members"].append(n)
                c["lat"] = sum(m["lat"] for m in c["members"]) / len(c["members"])
                c["lon"] = sum(m["lon"] for m in c["members"]) / len(c["members"])
                break
        else:
            clusters.append({"lat": n["lat"], "lon": n["lon"], "members": [n]})
    return clusters


def main() -> None:
    nodes = overpass(QUERY)["elements"]
    clusters = merge_nearby(sorted(nodes, key=lambda n: n["id"]))

    signals = []
    for c in clusters:
        tags = [m.get("tags", {}) for m in c["members"]]
        name = next((t["name"] for t in tags if t.get("name")), None)
        signals.append({
            "id": min(m["id"] for m in c["members"]),  # stable OSM node id
            "lat": round(c["lat"], 6),
            "lon": round(c["lon"], 6),
            "name": name,
            "points": len(c["members"]),
            "countdown": any(t.get("traffic_signals:countdown") == "yes" for t in tags),
        })

    signals.sort(key=lambda s: s["id"])
    OUT_PATH.write_text(json.dumps(signals, separators=(",", ":"), ensure_ascii=False))
    print(f"Saved {len(signals)} signals (merged from {len(nodes)} OSM points) to {OUT_PATH}")


if __name__ == "__main__":
    main()
