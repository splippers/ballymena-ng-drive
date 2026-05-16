#!/usr/bin/env python3
"""Parse OSM footways, cycleways, paths and steps into thin BeamNG DecalRoads.

Reads from ballymena_osm_raw.json directly (footways were fetched by
fetch_osm.py's highway query but filtered out by parse_roads.py).
"""
import json, os, uuid
from utils import latlon_to_meters, get_bbox_meters, clip_polyline

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'osm')
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')
os.makedirs(OUT_DIR, exist_ok=True)

# Lighter-coloured asphalt variant makes pavements visually distinct from roads
FOOTWAY_MATERIAL = 'AsphaltRoad_variation_02'
CYCLEWAY_MATERIAL = 'AsphaltRoad_variation_01'

WIDTHS = {
    'footway':    1.5,
    'path':       1.2,
    'steps':      1.8,
    'bridleway':  2.0,
    'cycleway':   2.5,
    'pedestrian': 4.0,
}

INCLUDE = frozenset(WIDTHS)


def extract_footways(elements, nodes):
    ways = []
    for el in elements:
        if el['type'] != 'way':
            continue
        hw = el.get('tags', {}).get('highway', '')
        if hw not in INCLUDE:
            continue
        nd = [{'id': nid, 'lat': nodes[nid][0], 'lon': nodes[nid][1]}
              for nid in el.get('nodes', []) if nid in nodes]
        if len(nd) < 2:
            continue
        tags = el.get('tags', {})
        ways.append({
            'highway': hw,
            'name': tags.get('name', ''),
            'surface': tags.get('surface', ''),
            'nodes': nd,
        })
    return ways


def generate_footway_decals(ways):
    x_min, x_max, y_min, y_max = get_bbox_meters()
    output = []
    for way in ways:
        hw = way['highway']
        pts = [(n['lon'], n['lat']) for n in way['nodes']]
        local = [latlon_to_meters(lat, lon) for lon, lat in pts]
        segs = clip_polyline(local, x_min, x_max, y_min, y_max)
        for seg in segs:
            if len(seg) < 2:
                continue
            width = WIDTHS.get(hw, 1.5)
            mat = CYCLEWAY_MATERIAL if hw == 'cycleway' else FOOTWAY_MATERIAL
            nodes = [[round(x, 2), round(y, 2), 0.0, width] for x, y in seg]
            obj = {
                'class': 'DecalRoad',
                'persistentId': str(uuid.uuid4()),
                '__parent': 'Footways',
                'position': nodes[0][:3],
                'improvedSpline': True,
                'breakAngle': 20,
                'distanceFade': [120, 20],
                'renderPriority': 4,   # below main roads (5)
                'overObjects': True,
                'useTemplate': True,
                'material': mat,
                'highway': hw,
                'nodes': nodes,
                'startEndFade': [round(width * 0.4, 1), round(width * 0.4, 1)],
                'textureLength': max(1, round(width * 3)),
            }
            name = way.get('name', '').strip()
            if name:
                obj['name'] = name
            output.append(obj)
    return output


def main():
    raw_path = os.path.join(DATA_DIR, 'ballymena_osm_raw.json')
    if not os.path.exists(raw_path):
        print('Run fetch_osm.py first!')
        return

    with open(raw_path) as f:
        data = json.load(f)

    elements = data.get('elements', [])
    nodes_map = {el['id']: (el['lat'], el['lon'])
                 for el in elements if el['type'] == 'node'}
    ways = extract_footways(elements, nodes_map)

    from collections import Counter
    types = Counter(w['highway'] for w in ways)
    print(f'Footway ways: {len(ways)}')
    for hw, cnt in types.most_common():
        print(f'  {hw}: {cnt}')

    decals = generate_footway_decals(ways)
    out_path = os.path.join(OUT_DIR, 'footway_roads.ndjson')
    with open(out_path, 'w') as f:
        for obj in decals:
            f.write(json.dumps(obj, separators=(',', ':')) + '\n')

    print(f'Generated {len(decals)} footway DecalRoad objects → {out_path}')


if __name__ == '__main__':
    main()
