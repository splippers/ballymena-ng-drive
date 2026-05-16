#!/usr/bin/env python3
"""Convert OSM road data to BeamNG DecalRoad NDJSON, clipped to BBOX."""
import json, os, math, uuid
from utils import latlon_to_meters, road_width, get_bbox_meters, clip_polyline

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'osm')
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')
os.makedirs(OUT_DIR, exist_ok=True)

# Material per highway class — uses BeamNG engine-provided asphalt/concrete decals.
# Service/pedestrian upgraded from DirtRoad to proper asphalt variants.
_HIGHWAY_MATERIAL = {
    'motorway': 'AsphaltRoad_variation_01',
    'trunk': 'AsphaltRoad_variation_01',
    'primary': 'AsphaltRoad_variation_01',
    'secondary': 'AsphaltRoad_variation_01',
    'tertiary': 'AsphaltRoad_variation_02',
    'unclassified': 'AsphaltRoad_variation_03',
    'residential': 'AsphaltRoad_variation_03',
    'living_street': 'AsphaltRoad_variation_03',
    'service': 'AsphaltRoad_variation_03',
    'pedestrian': 'AsphaltRoad_variation_02',
}
_SURFACE_MATERIAL = {
    'asphalt': 'AsphaltRoad_variation_01',
    'paved': 'AsphaltRoad_variation_02',
    'concrete': 'AsphaltRoad_variation_02',
    'paving_stones': 'AsphaltRoad_variation_02',
    'sett': 'AsphaltRoad_variation_02',
    'cobblestone': 'AsphaltRoad_variation_02',
    'compacted': 'AsphaltRoad_variation_03',
    'unpaved': 'AsphaltRoad_variation_03',
    'ground': 'AsphaltRoad_variation_03',
    'dirt': 'AsphaltRoad_variation_03',
    'gravel': 'AsphaltRoad_variation_03',
}
_DEFAULT_MATERIAL = 'AsphaltRoad_variation_01'


def material_for_road(highway, surface=''):
    if surface and surface in _SURFACE_MATERIAL:
        return _SURFACE_MATERIAL[surface]
    if highway in _HIGHWAY_MATERIAL:
        return _HIGHWAY_MATERIAL[highway]
    if highway.endswith('_link'):
        base = highway[:-5]
        if base in _HIGHWAY_MATERIAL:
            return _HIGHWAY_MATERIAL[base]
    return _DEFAULT_MATERIAL


def simplify_polyline(pts, tolerance=0.5):
    """Douglas-Peucker — reduce point count while preserving shape."""
    if len(pts) <= 2:
        return pts

    def pt_line_dist(p, a, b):
        if a == b:
            return math.hypot(p[0] - a[0], p[1] - a[1])
        t = ((p[0]-a[0])*(b[0]-a[0]) + (p[1]-a[1])*(b[1]-a[1])) / max(
            (b[0]-a[0])**2 + (b[1]-a[1])**2, 1e-12)
        t = max(0.0, min(1.0, t))
        px, py = a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])
        return math.hypot(p[0]-px, p[1]-py)

    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = pt_line_dist(pts[i], pts[0], pts[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > tolerance:
        left = simplify_polyline(pts[:idx+1], tolerance)
        right = simplify_polyline(pts[idx:], tolerance)
        return left[:-1] + right
    return [pts[0], pts[-1]]


def build_decal_road(pts_local, highway, surface, lanes, name):
    """Return a DecalRoad dict from a local-metre polyline, or None if degenerate."""
    width = road_width(highway, lanes)
    mat = material_for_road(highway, surface)
    pts = simplify_polyline(pts_local, tolerance=0.5)
    if len(pts) < 2:
        return None
    nodes = [[round(x, 2), round(y, 2), 0.0, width] for x, y in pts]
    obj = {
        'class': 'DecalRoad',
        'persistentId': str(uuid.uuid4()),
        '__parent': 'DecalRoads',
        'position': nodes[0][:3],
        'improvedSpline': True,
        'breakAngle': 10,
        'distanceFade': [300, 50],
        'renderPriority': 5,
        'overObjects': True,
        'useTemplate': True,
        'material': mat,
        'highway': highway,   # preserved for layermap / preview (not read by BeamNG)
        'nodes': nodes,
        'startEndFade': [round(width * 0.8, 1), round(width * 0.8, 1)],
        'textureLength': max(1, round(width * 2.5)),
    }
    if name:
        obj['name'] = name
    return obj


def generate_decal_roads(roads):
    x_min, x_max, y_min, y_max = get_bbox_meters()
    output = []
    for road in roads:
        pts = [(n['lon'], n['lat']) for n in road['nodes']]
        if len(pts) < 2:
            continue
        local = [latlon_to_meters(lat, lon) for lon, lat in pts]
        clipped_segs = clip_polyline(local, x_min, x_max, y_min, y_max)
        for seg in clipped_segs:
            if len(seg) < 2:
                continue
            dr = build_decal_road(seg, road['highway'],
                                  road.get('surface', ''),
                                  road.get('lanes', ''),
                                  road.get('name', '').strip())
            if dr:
                output.append(dr)
    return output


def main():
    roads_path = os.path.join(DATA_DIR, 'ballymena_roads.json')
    if not os.path.exists(roads_path):
        print('Run fetch_osm.py first!')
        return

    with open(roads_path) as f:
        roads = json.load(f)

    print(f'Processing {len(roads)} roads …')
    decal_roads = generate_decal_roads(roads)

    out_path = os.path.join(OUT_DIR, 'decal_roads.ndjson')
    with open(out_path, 'w') as f:
        for dr in decal_roads:
            f.write(json.dumps(dr, separators=(',', ':')) + '\n')

    print(f'  Generated {len(decal_roads)} DecalRoad objects (clipped to BBOX)')
    print(f'  Saved: {out_path}')

    unique_names = sorted({r.get('name','') for r in roads if r.get('name')})
    print(f'\n  Named streets ({len(unique_names)}):')
    for name in unique_names:
        cnt = sum(1 for r in roads if r.get('name') == name)
        print(f'    {name}: {cnt} segment(s)')


if __name__ == '__main__':
    main()
