#!/usr/bin/env python3
"""Parse OSM feature polygons (parking lots, parks, waterways) for terrain painting.

Reads ballymena_features.json produced by fetch_osm.py.
Outputs feature_polygons.ndjson — a list of polygon paint records consumed by build_map.py
to fill the terrain layermap before road painting runs on top.
"""
import json, os
from utils import latlon_to_meters, get_bbox_meters

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'osm')
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')
os.makedirs(OUT_DIR, exist_ok=True)

# Layer indices matching the .ter materials list: ['Grass', 'Dirt', 'Asphalt']
LAYER_GRASS   = 0
LAYER_DIRT    = 1
LAYER_ASPHALT = 2

KIND_LAYER = {
    'amenity:parking':          LAYER_ASPHALT,
    'waterway:river':           LAYER_DIRT,
    'waterway:stream':          LAYER_DIRT,
    'waterway:canal':           LAYER_DIRT,
    'natural:water':            LAYER_DIRT,
    'leisure:park':             LAYER_GRASS,
    'leisure:recreation_ground':LAYER_GRASS,
    'leisure:garden':           LAYER_GRASS,
    'landuse:grass':            LAYER_GRASS,
    'landuse:recreation_ground':LAYER_GRASS,
    'landuse:park':             LAYER_GRASS,
    'landuse:village_green':    LAYER_GRASS,
}


def polygon_centroid(pts):
    return (sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts))


def generate_feature_polygons(features):
    x_min, x_max, y_min, y_max = get_bbox_meters()
    out = []
    for feat in features:
        kind = feat.get('kind', '')
        layer = KIND_LAYER.get(kind)
        if layer is None:
            continue
        pts = [latlon_to_meters(n['lat'], n['lon']) for n in feat.get('nodes', [])]
        if len(pts) < 3:
            continue
        cx, cy = polygon_centroid(pts)
        if not (x_min <= cx <= x_max and y_min <= cy <= y_max):
            continue
        out.append({
            'kind': kind,
            'layer': layer,
            'name': feat.get('name', ''),
            'pts': [[round(x, 2), round(y, 2)] for x, y in pts],
        })
    return out


def main():
    feat_path = os.path.join(DATA_DIR, 'ballymena_features.json')
    if not os.path.exists(feat_path):
        print('No ballymena_features.json — run fetch_osm.py first, then re-run process.')
        out_path = os.path.join(OUT_DIR, 'feature_polygons.ndjson')
        open(out_path, 'w').close()
        print(f'  Created empty {out_path}')
        return

    with open(feat_path) as f:
        features = json.load(f)

    print(f'Processing {len(features)} feature polygons …')
    polys = generate_feature_polygons(features)

    out_path = os.path.join(OUT_DIR, 'feature_polygons.ndjson')
    with open(out_path, 'w') as f:
        for p in polys:
            f.write(json.dumps(p, separators=(',', ':')) + '\n')

    from collections import Counter
    kinds = Counter(p['kind'] for p in polys)
    print(f'  Generated {len(polys)} polygons:')
    for k, c in kinds.most_common():
        lname = {0: 'grass', 1: 'dirt', 2: 'asphalt'}.get(KIND_LAYER.get(k, -1), '?')
        print(f'    {k} → {lname}: {c}')
    print(f'  Saved: {out_path}')


if __name__ == '__main__':
    main()
