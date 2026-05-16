#!/usr/bin/env python3
"""Convert OSM building footprints to BeamNG TSStatic objects, clipped to BBOX."""
import json, os, math, uuid
from utils import latlon_to_meters, get_bbox_meters

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'osm')
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')
os.makedirs(OUT_DIR, exist_ok=True)

SHAPE_PATH = '/levels/ballymena/art/shapes/buildings/box.dae'
STOREY_HEIGHT = 3.0


def polygon_centroid(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def oriented_bbox(pts):
    """Oriented bounding box of polygon. Returns (cx,cz), width, depth, angle_rad."""
    cx, cz = polygon_centroid(pts)
    c = [(x - cx, z - cz) for x, z in pts]
    cov_xx = sum(x*x for x, _ in c) / len(c)
    cov_zz = sum(z*z for _, z in c) / len(c)
    cov_xz = sum(x*z for x, z in c) / len(c)
    tr = cov_xx + cov_zz
    det = cov_xx * cov_zz - cov_xz**2
    d = max(0.0, tr*tr - 4*det)
    eig1 = (tr + math.sqrt(d)) / 2
    angle = (math.atan2(eig1 - cov_xx, cov_xz) if abs(cov_xz) > 1e-10
             else (0.0 if cov_xx >= cov_zz else math.pi / 2))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    proj = [x * cos_a + z * sin_a for x, z in c]
    perp = [-x * sin_a + z * cos_a for x, z in c]
    min_p, max_p = min(proj), max(proj)
    min_pp, max_pp = min(perp), max(perp)
    cx += (min_p + max_p) / 2 * cos_a - (min_pp + max_pp) / 2 * sin_a
    cz += (min_p + max_p) / 2 * sin_a + (min_pp + max_pp) / 2 * cos_a
    return (cx, cz), max_p - min_p, max_pp - min_pp, angle


def building_height(b, area):
    h = b.get('height', '')
    if h:
        try:
            return max(float(h.replace('m', '').strip()), 3.0)
        except ValueError:
            pass
    levels = b.get('levels', 0)
    if levels <= 0:
        levels = 3 if area > 2000 else 2 if area > 50 else 1
    return max(levels * STOREY_HEIGHT, 3.0)


def generate_buildings(buildings):
    x_min, x_max, y_min, y_max = get_bbox_meters()
    objects = []
    for b in buildings:
        pts = [latlon_to_meters(n['lat'], n['lon']) for n in b['nodes']]
        pts = [(p[0], p[1]) for p in pts]
        if len(pts) < 3:
            continue
        if pts[0] != pts[-1]:
            pts = pts + [pts[0]]
        (cx, cz), width, depth, angle = oriented_bbox(pts)
        # Skip buildings whose centroid is outside BBOX
        if cx < x_min or cx > x_max or cz < y_min or cz > y_max:
            continue
        area = width * depth
        if area < 4.0:
            continue
        height = building_height(b, area)
        width = max(width, 1.0)
        depth = max(depth, 1.0)
        height = max(height, 1.0)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        rot = [cos_a, sin_a, 0, -sin_a, cos_a, 0, 0, 0, 1]
        obj = {
            'class': 'TSStatic',
            'persistentId': str(uuid.uuid4()),
            '__parent': 'buildings_group',
            # Z is set to height/2 here (base at Z=0); build_map.py adjusts for terrain height
            'position': [round(cx, 2), round(cz, 2), round(height / 2, 2)],
            'shapeName': SHAPE_PATH,
            'scale': [round(width, 2), round(depth, 2), round(height, 2)],
            'rotationMatrix': rot,
            'useInstanceRenderData': True,
            'annotation': 'BUILDINGS',
        }
        name = b.get('name', '').strip()
        if name:
            obj['name'] = name
        objects.append(obj)
    return objects


def main():
    build_path = os.path.join(DATA_DIR, 'ballymena_buildings.json')
    if not os.path.exists(build_path):
        print('Run fetch_osm.py first!')
        return

    with open(build_path) as f:
        buildings = json.load(f)

    print(f'Processing {len(buildings)} building footprints …')
    items = generate_buildings(buildings)
    print(f'  Generated {len(items)} TSStatic objects (BBOX-clipped)')

    out_path = os.path.join(OUT_DIR, 'buildings.ndjson')
    with open(out_path, 'w') as f:
        for obj in items:
            f.write(json.dumps(obj, separators=(',', ':')) + '\n')
    print(f'  Saved: {out_path}')

    named = [b for b in buildings if b.get('name')]
    if named:
        print(f'\n  Named buildings ({len(named)}):')
        for b in named[:20]:
            print(f'    {b["name"]} ({b.get("building","?")})')


if __name__ == '__main__':
    main()
