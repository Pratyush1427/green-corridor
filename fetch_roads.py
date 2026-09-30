"""Downloads Bengaluru's main road network from OpenStreetMap into data/roads.json.gz.

Run once (or whenever you want fresh data):  python fetch_roads.py
If the public Overpass server keeps timing out, save the query result yourself and run:
    python fetch_roads.py --input roads_raw.json
Data (c) OpenStreetMap contributors, ODbL.

Only main roads (motorway down to tertiary/unclassified) are included, to keep the file small.
Ambulances dropped on a side street start from the nearest main-road junction.

Output format (compact, for routing.py):
    nodes: [[lat, lon], ...]          junctions and dead ends (the routing graph's vertices)
    edges: [[u, v, oneway, speed_kmh, length_m, [lat, lon, lat, lon, ...]], ...]
           u, v index into nodes; the flat list is the road shape between them (excluding u, v)
"""
import argparse
import gzip
import json
import re
from pathlib import Path
from typing import Optional

from osm import BBOX, distance_m, overpass

ROAD_TYPES = (
    "motorway|trunk|primary|secondary|tertiary|unclassified|"
    "motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"
)
QUERY = f'[out:json][timeout:180];way["highway"~"^({ROAD_TYPES})$"]({BBOX});out body;>;out skel qt;'
OUT_PATH = Path(__file__).parent / "data" / "roads.json.gz"

# Typical free-flow speeds (km/h) by road type, used when a road has no maxspeed tag.
DEFAULT_SPEED = {
    "motorway": 70, "trunk": 50, "primary": 40, "secondary": 35, "tertiary": 30,
    "unclassified": 25, "motorway_link": 40, "trunk_link": 30, "primary_link": 30,
    "secondary_link": 25, "tertiary_link": 25,
}


def speed_kmh(tags: dict) -> float:
    m = re.match(r"^\s*(\d+)", tags.get("maxspeed", ""))
    if m and 10 <= int(m.group(1)) <= 120:
        return float(m.group(1))
    return float(DEFAULT_SPEED.get(tags.get("highway"), 25))


def oneway(tags: dict) -> Optional[str]:
    """Returns 'forward', 'reverse' or None (two-way)."""
    value = tags.get("oneway")
    if value in ("yes", "true", "1"):
        return "forward"
    if value == "-1":
        return "reverse"
    if value == "no":
        return None
    if tags.get("highway") == "motorway" or tags.get("junction") in ("roundabout", "circular"):
        return "forward"
    return None


def build_graph(elements: list) -> dict:
    coords = {e["id"]: (e["lat"], e["lon"]) for e in elements if e["type"] == "node"}
    ways = [e for e in elements if e["type"] == "way" and len(e.get("nodes", [])) >= 2]

    # A point becomes a graph vertex if it's a way's end or shared by several ways (a junction).
    uses = {}
    for w in ways:
        for n in w["nodes"]:
            uses[n] = uses.get(n, 0) + 1
    is_vertex = set(n for n, count in uses.items() if count > 1)
    for w in ways:
        is_vertex.update((w["nodes"][0], w["nodes"][-1]))

    index = {}
    nodes = []

    def vertex(osm_id: int) -> int:
        if osm_id not in index:
            index[osm_id] = len(nodes)
            lat, lon = coords[osm_id]
            nodes.append([round(lat, 6), round(lon, 6)])
        return index[osm_id]

    edges = []
    for w in ways:
        tags = w.get("tags", {})
        direction = oneway(tags)
        ids = [n for n in w["nodes"] if n in coords]
        if direction == "reverse":
            ids.reverse()
        speed = speed_kmh(tags)
        start = 0
        for i in range(1, len(ids)):
            if ids[i] not in is_vertex and i != len(ids) - 1:
                continue
            segment = ids[start:i + 1]
            length = sum(distance_m(*coords[a], *coords[b]) for a, b in zip(segment, segment[1:]))
            if length > 0:
                shape = [round(x, 6) for n in segment[1:-1] for x in coords[n]]
                edges.append([vertex(segment[0]), vertex(segment[-1]), int(direction is not None),
                              speed, round(length, 1), shape])
            start = i

    return {"nodes": nodes, "edges": edges}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", help="use an already-downloaded Overpass JSON file")
    args = parser.parse_args()

    if args.input:
        data = json.loads(Path(args.input).read_text())
    else:
        data = overpass(QUERY, timeout=300)
    graph = build_graph(data["elements"])

    OUT_PATH.parent.mkdir(exist_ok=True)
    with gzip.open(OUT_PATH, "wt") as f:
        json.dump(graph, f, separators=(",", ":"))
    size_mb = OUT_PATH.stat().st_size / 1e6
    print(f"Saved {len(graph['nodes'])} junctions and {len(graph['edges'])} road segments "
          f"to {OUT_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
