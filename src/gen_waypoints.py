#!/usr/bin/env python3
"""Build a BeamNGWaypoint intersection graph from the road network.

Algorithm
---------
1. Collect every road-segment endpoint (first + last node of each DecalRoad).
2. Snap positions to a 1 m grid to detect shared junction nodes.
3. Any grid cell reached by endpoints from ≥ 2 distinct road segments is a
   junction; place one BeamNGWaypoint there.
4. Also emit a small set of *named* waypoints at the first node of key named
   streets so the player UI can show landmark names.

Output
------
waypoints.ndjson — one BeamNGWaypoint JSON object per line.
"""
import json, os, uuid
from collections import defaultdict

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')

SNAP = 1.0    # metres — grid cell size for junction detection
WP_RADIUS = 5.0

# Named streets whose first node becomes a labelled landmark waypoint.
LANDMARK_ROADS = {
    'Bridge Street':      'wp_bridge_street',
    'Ballymoney Road':    'wp_ballymoney_road',
    'Broughshane Road':   'wp_broughshane_road',
    'Galgorm Road':       'wp_galgorm_road',
    'Waveney Road':       'wp_waveney_road',
    'Ballymoney Street':  'wp_ballymoney_street',
}


def snap_key(x, y):
    return (round(x / SNAP) * SNAP, round(y / SNAP) * SNAP)


def find_junctions(roads):
    """Return list of (x, y, z) average positions for junctions."""
    # Map each grid cell to a list of (road_idx, x, y, z) entries
    cell_entries = defaultdict(list)
    for ridx, road in enumerate(roads):
        nodes = road.get('nodes', [])
        if not nodes:
            continue
        for node in (nodes[0], nodes[-1]):
            x, y = node[0], node[1]
            z = node[2] if len(node) > 2 else 0.0
            cell_entries[snap_key(x, y)].append((ridx, x, y, z))

    junctions = []
    for entries in cell_entries.values():
        road_set = {e[0] for e in entries}
        if len(road_set) >= 2:
            avg_x = sum(e[1] for e in entries) / len(entries)
            avg_y = sum(e[2] for e in entries) / len(entries)
            avg_z = sum(e[3] for e in entries) / len(entries)
            junctions.append((avg_x, avg_y, avg_z))
    return junctions


def find_landmark_positions(roads):
    """Return {wp_name: (x, y, z)} for key named streets."""
    positions = {}
    for road in roads:
        name = road.get('name', '')
        if name not in LANDMARK_ROADS:
            continue
        wp_name = LANDMARK_ROADS[name]
        if wp_name in positions:
            continue
        nodes = road.get('nodes', [])
        if not nodes:
            continue
        n = nodes[len(nodes) // 2]  # mid-segment node
        positions[wp_name] = (n[0], n[1], n[2] if len(n) > 2 else 0.0)
    return positions


def make_waypoints(junctions, landmarks):
    out = []
    # Junction waypoints (unnamed, used by AI)
    for i, (x, y, z) in enumerate(junctions):
        out.append({
            'class': 'BeamNGWaypoint',
            'name': f'wp_{i:04d}',
            'persistentId': str(uuid.uuid4()),
            '__parent': 'Waypoints',
            'position': [round(x, 2), round(y, 2), round(z + 0.1, 2)],
            'radius': WP_RADIUS,
            'normalRadius': WP_RADIUS,
        })
    # Named landmark waypoints (shown in player HUD)
    for wp_name, (x, y, z) in sorted(landmarks.items()):
        out.append({
            'class': 'BeamNGWaypoint',
            'name': wp_name,
            'persistentId': str(uuid.uuid4()),
            '__parent': 'Waypoints',
            'position': [round(x, 2), round(y, 2), round(z + 0.5, 2)],
            'radius': 15.0,
            'normalRadius': 15.0,
        })
    return out


def main():
    roads_path = os.path.join(OUT_DIR, 'decal_roads.ndjson')
    if not os.path.exists(roads_path):
        print('Run parse_roads.py first!')
        return

    with open(roads_path) as f:
        roads = [json.loads(line) for line in f if line.strip()]

    print(f'Building waypoints from {len(roads)} road segments …')
    junctions = find_junctions(roads)
    landmarks = find_landmark_positions(roads)
    wps = make_waypoints(junctions, landmarks)

    out_path = os.path.join(OUT_DIR, 'waypoints.ndjson')
    with open(out_path, 'w') as f:
        for wp in wps:
            f.write(json.dumps(wp, separators=(',', ':')) + '\n')

    print(f'  Junctions: {len(junctions)}')
    print(f'  Landmarks: {len(landmarks)} ({", ".join(sorted(landmarks))})')
    print(f'  Total waypoints: {len(wps)} → {out_path}')


if __name__ == '__main__':
    main()
