"""Traffic-aware ambulance routing on the road graph built by fetch_roads.py.

Travel times come from each road's free-flow speed, slowed by the typical congestion at the
nearest monitored junction for the chosen hour. Two scenarios are compared:

- normal:   the ambulance drives in ordinary traffic and waits at red signals
- corridor: signals ahead are turned green and traffic on the route is cleared

The corridor model is deliberately simple (see the constants below). It's a starting point
for experiments, not a validated traffic model.
"""
import gzip
import heapq
import json
import math
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import db
from config import JUNCTIONS
from osm import distance_m

BASE_DIR = Path(__file__).parent
ROADS_PATH = BASE_DIR / "data" / "roads.json.gz"
HOSPITALS_PATH = BASE_DIR / "static" / "hospitals.json"
SIGNALS_PATH = BASE_DIR / "static" / "signals.json"

# ---- model assumptions (tweak these to experiment) ----
JUNCTION_RADIUS_M = 2000        # a road uses the congestion of a monitored junction this close
UNMONITORED_SHARE = 0.6         # roads far from any junction get this share of the city average
MIN_NORMAL_SPEED_SHARE = 0.15   # even in a jam, traffic creeps at 15% of free-flow speed
CORRIDOR_CONGESTION_SHARE = 1 / 3  # with a corridor, the ambulance feels 1/3 of the congestion
SIGNAL_CYCLE_S, SIGNAL_RED_S = 90, 46  # must match the simulated cycle in static/index.html
EXPECTED_RED_WAIT_S = SIGNAL_RED_S ** 2 / (2 * SIGNAL_CYCLE_S)  # average wait when arriving at random
SIGNAL_MATCH_M = 30             # a signal this close to the route counts as "on the route"
MAX_SNAP_M = 3000               # drop points further than this from a main road are rejected

GRID = 0.01  # degrees (~1 km) per spatial index cell


class RouteError(Exception):
    pass


def _cell(lat: float, lon: float) -> Tuple[int, int]:
    return int(lat // GRID), int(lon // GRID)


def _nearby_cells(lat: float, lon: float, rings: int = 1):
    ci, cj = _cell(lat, lon)
    for di in range(-rings, rings + 1):
        for dj in range(-rings, rings + 1):
            yield ci + di, cj + dj


class RoadGraph:
    def __init__(self) -> None:
        if not ROADS_PATH.exists():
            raise RouteError("Road data missing. Run: python fetch_roads.py")
        with gzip.open(ROADS_PATH, "rt") as f:
            raw = json.load(f)
        self.nodes: List[List[float]] = raw["nodes"]
        self.edges: List[list] = raw["edges"]

        # out[u] = [(v, edge_index, forward?)]
        self.out: Dict[int, List[Tuple[int, int, bool]]] = defaultdict(list)
        for i, (u, v, oneway, *_rest) in enumerate(self.edges):
            self.out[u].append((v, i, True))
            if not oneway:
                self.out[v].append((u, i, False))

        # Only snap to the largest strongly connected part, so every route exists.
        self.connected = self._largest_scc()
        self.grid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        for n in self.connected:
            self.grid[_cell(*self.nodes[n])].append(n)

        # Which monitored junction (if any) each road takes its congestion from.
        self.edge_junction: List[Optional[str]] = []
        for u, v, *_rest in self.edges:
            mid_lat = (self.nodes[u][0] + self.nodes[v][0]) / 2
            mid_lon = (self.nodes[u][1] + self.nodes[v][1]) / 2
            best, best_d = None, JUNCTION_RADIUS_M
            for j in JUNCTIONS:
                d = distance_m(mid_lat, mid_lon, j["lat"], j["lon"])
                if d < best_d:
                    best, best_d = j["id"], d
            self.edge_junction.append(best)

        hospitals = json.loads(HOSPITALS_PATH.read_text()) if HOSPITALS_PATH.exists() else []
        self.er_hospitals = [h for h in hospitals if h["emergency"]]
        self.hospital_vertex = {}
        for h in self.er_hospitals:
            v, _ = self.snap(h["lat"], h["lon"])
            self.hospital_vertex.setdefault(v, h)

        self.signals = json.loads(SIGNALS_PATH.read_text()) if SIGNALS_PATH.exists() else []
        self.signal_grid: Dict[Tuple[int, int], List[dict]] = defaultdict(list)
        for s in self.signals:
            self.signal_grid[_cell(s["lat"], s["lon"])].append(s)
        # Vertices with a signal, so the "normal" route choice accounts for red-light waits.
        self.signal_vertices = set()
        for s in self.signals:
            v, d = self.snap(s["lat"], s["lon"])
            if d <= SIGNAL_MATCH_M:
                self.signal_vertices.add(v)

    def _largest_scc(self) -> set:
        """Kosaraju's algorithm, iterative (the graph is too deep for recursion)."""
        n = len(self.nodes)
        rev: Dict[int, List[int]] = defaultdict(list)
        for u in range(n):
            for v, _, _ in self.out[u]:
                rev[v].append(u)

        order, seen = [], [False] * n
        for root in range(n):
            if seen[root]:
                continue
            seen[root] = True
            stack = [(root, iter(self.out[root]))]
            while stack:
                u, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    stack.pop()
                    order.append(u)
                elif not seen[nxt[0]]:
                    seen[nxt[0]] = True
                    stack.append((nxt[0], iter(self.out[nxt[0]])))

        comp, best = [-1] * n, set()
        for root in reversed(order):
            if comp[root] != -1:
                continue
            members, stack = [], [root]
            comp[root] = root
            while stack:
                u = stack.pop()
                members.append(u)
                for v in rev[u]:
                    if comp[v] == -1:
                        comp[v] = root
                        stack.append(v)
            if len(members) > len(best):
                best = set(members)
        return best

    def snap(self, lat: float, lon: float) -> Tuple[int, float]:
        """Nearest connected junction and its distance in metres."""
        for rings in (1, 3, 10):
            candidates = [n for c in _nearby_cells(lat, lon, rings) for n in self.grid.get(c, [])]
            if candidates:
                best = min(candidates, key=lambda n: distance_m(lat, lon, *self.nodes[n]))
                return best, distance_m(lat, lon, *self.nodes[best])
        raise RouteError("That point is outside the mapped area.")

    # ---------- costs ----------

    def edge_congestion(self, typical: Dict[str, float], city_avg: float) -> List[float]:
        return [
            typical.get(j, city_avg) if j else city_avg * UNMONITORED_SHARE
            for j in self.edge_junction
        ]

    def edge_seconds(self, i: int, congestion: float, corridor: bool) -> float:
        speed_kmh, length_m = self.edges[i][3], self.edges[i][4]
        if corridor:
            share = max(0.5, 1 - congestion * CORRIDOR_CONGESTION_SHARE)
        else:
            share = max(MIN_NORMAL_SPEED_SHARE, 1 - congestion)
        return length_m / (speed_kmh * share / 3.6)

    def shortest(self, start: int, targets: set, costs: List[float], corridor: bool):
        """Dijkstra from start until the first target is reached. Returns (target, [(edge, forward)])."""
        dist = {start: 0.0}
        prev: Dict[int, Tuple[int, int, bool]] = {}
        heap = [(0.0, start)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, math.inf):
                continue
            if u in targets:
                path, node = [], u
                while node != start:
                    p, e, fwd = prev[node]
                    path.append((e, fwd))
                    node = p
                return u, list(reversed(path))
            for v, e, fwd in self.out[u]:
                nd = d + costs[e]
                if not corridor and v in self.signal_vertices:
                    nd += EXPECTED_RED_WAIT_S
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = (u, e, fwd)
                    heapq.heappush(heap, (nd, v))
        raise RouteError("No route found.")

    # ---------- route details ----------

    def edge_shape(self, e: int, forward: bool) -> List[List[float]]:
        u, v, _, _, _, flat = self.edges[e]
        pts = [self.nodes[u]] + [flat[k:k + 2] for k in range(0, len(flat), 2)] + [self.nodes[v]]
        return pts if forward else pts[::-1]

    def describe(self, path: List[Tuple[int, bool]], edge_time: List[float]) -> dict:
        """Coordinates, cumulative time at each coordinate, and the signals along the path."""
        coords: List[List[float]] = []
        times: List[float] = []
        along: List[float] = []
        t = dist = 0.0
        for e, fwd in path:
            pts = self.edge_shape(e, fwd)
            seg_lengths = [distance_m(*a, *b) for a, b in zip(pts, pts[1:])]
            total = sum(seg_lengths) or 1.0
            if not coords:
                coords.append(pts[0]); times.append(t); along.append(dist)
            for p, seg in zip(pts[1:], seg_lengths):
                t += edge_time[e] * seg / total
                dist += seg
                coords.append(p); times.append(round(t, 1)); along.append(dist)
        return {"coords": coords, "times": times, "along": along,
                "distance_m": round(dist), "travel_s": t, "signals": self.signals_on(coords, along)}

    def signals_on(self, coords: List[List[float]], along: List[float]) -> List[dict]:
        found: Dict[int, dict] = {}
        for k in range(len(coords) - 1):
            (lat1, lon1), (lat2, lon2) = coords[k], coords[k + 1]
            seg = along[k + 1] - along[k]
            for c in set(_nearby_cells(lat1, lon1)) | set(_nearby_cells(lat2, lon2)):
                for s in self.signal_grid.get(c, []):
                    # Project the signal onto the segment (flat-earth approximation is fine here).
                    kx = math.cos(math.radians(lat1)) * 111320
                    ax, ay = (lon2 - lon1) * kx, (lat2 - lat1) * 110540
                    px, py = (s["lon"] - lon1) * kx, (s["lat"] - lat1) * 110540
                    frac = 0.0 if seg == 0 else max(0.0, min(1.0, (px * ax + py * ay) / (ax * ax + ay * ay or 1)))
                    d = math.hypot(px - frac * ax, py - frac * ay)
                    if d <= SIGNAL_MATCH_M and (s["id"] not in found or d < found[s["id"]]["_d"]):
                        found[s["id"]] = {"id": s["id"], "lat": s["lat"], "lon": s["lon"], "name": s.get("name"),
                                          "along_m": round(along[k] + frac * seg), "_d": d}
        result = sorted(found.values(), key=lambda s: s["along_m"])
        for s in result:
            del s["_d"]
        return result


@lru_cache(maxsize=1)
def graph() -> RoadGraph:
    return RoadGraph()


def time_at(route: dict, along_m: float) -> float:
    """Interpolated travel time at a distance along a described route."""
    along, times = route["along"], route["times"]
    k = min(max(0, next((i for i, a in enumerate(along) if a >= along_m), len(along) - 1)), len(along) - 1)
    if k == 0:
        return times[0]
    a0, a1 = along[k - 1], along[k]
    frac = 0 if a1 == a0 else (along_m - a0) / (a1 - a0)
    return times[k - 1] + frac * (times[k] - times[k - 1])


def plan_route(start_lat: float, start_lon: float, hour: int,
               hospital: Optional[Tuple[float, float]] = None) -> dict:
    """Route an ambulance to a hospital (or the fastest emergency hospital if none given)."""
    g = graph()
    start, snap_m = g.snap(start_lat, start_lon)
    if snap_m > MAX_SNAP_M:
        raise RouteError("That point is too far from any main road.")

    rows = db.typical_at_hour(hour)
    typical = {r["junction_id"]: r["congestion"] or 0.0 for r in rows}
    city_avg = sum(typical.values()) / len(typical) if typical else 0.2
    congestion = g.edge_congestion(typical, city_avg)
    corridor_cost = [g.edge_seconds(i, c, True) for i, c in enumerate(congestion)]
    normal_cost = [g.edge_seconds(i, c, False) for i, c in enumerate(congestion)]

    if hospital is None:
        if not g.hospital_vertex:
            raise RouteError("No emergency hospitals loaded. Run: python fetch_hospitals.py")
        targets = set(g.hospital_vertex) - {start} or set(g.hospital_vertex)
    else:
        hv, _ = g.snap(*hospital)
        targets = {hv}

    end, corridor_path = g.shortest(start, targets, corridor_cost, corridor=True)
    if not corridor_path:
        raise RouteError("The ambulance is already at that hospital.")
    corridor = g.describe(corridor_path, corridor_cost)
    for s in corridor["signals"]:
        s["eta_s"] = round(time_at(corridor, s["along_m"]), 1)

    # Baseline: the best route a driver would pick without the corridor, to the same hospital.
    _, normal_path = g.shortest(start, {end}, normal_cost, corridor=False)
    normal = g.describe(normal_path, normal_cost)
    normal_eta = normal["travel_s"] + EXPECTED_RED_WAIT_S * len(normal["signals"])

    if hospital is None:
        dest = g.hospital_vertex[end]
    else:
        dest = {"name": "Selected destination", "lat": hospital[0], "lon": hospital[1], "phone": None}
        dest = next((h for h in g.er_hospitals if (h["lat"], h["lon"]) == tuple(hospital)), dest)

    return {
        "hour": hour,
        "start": g.nodes[start],
        "hospital": {k: dest.get(k) for k in ("name", "lat", "lon", "phone")},
        "coords": corridor["coords"],
        "times": corridor["times"],
        "distance_m": corridor["distance_m"],
        "eta_s": round(corridor["travel_s"]),
        "signals": corridor["signals"],
        "normal": {
            "coords": normal["coords"],
            "distance_m": normal["distance_m"],
            "eta_s": round(normal_eta),
            "signals": len(normal["signals"]),
        },
        "saved_s": round(normal_eta - corridor["travel_s"]),
    }
