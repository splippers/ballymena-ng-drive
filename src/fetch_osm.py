#!/usr/bin/env python3
"""Fetch OSM road, building, waterway and leisure data for Ballymena via Overpass."""
import json, urllib.request, urllib.error, urllib.parse, time, os
from collections import Counter
from utils import BBOX

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'osm')
os.makedirs(OUT_DIR, exist_ok=True)


def fetch_osm(query, label='data'):
    url = 'https://overpass-api.de/api/interpreter'
    data = urllib.parse.urlencode({'data': query}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, data=data, headers={'User-Agent': 'ballymena-ng-drive/0.1'})
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            print(f'  attempt {attempt+1} for {label} failed: {exc}')
            if attempt < 2:
                time.sleep(3)
    raise RuntimeError(f'Failed to fetch {label}')


def parse_nodes(elements):
    return {el['id']: (el['lat'], el['lon'])
            for el in elements if el['type'] == 'node'}


def extract_roads(elements, nodes):
    roads = []
    skip_hw = {'footway', 'path', 'cycleway', 'steps', 'bridleway',
               'track', 'corridor', 'proposed', 'construction'}
    for el in elements:
        if el['type'] != 'way':
            continue
        tags = el.get('tags', {})
        hw = tags.get('highway')
        if not hw or hw in skip_hw:
            continue
        nd = [{'id': nid, 'lat': nodes[nid][0], 'lon': nodes[nid][1]}
              for nid in el.get('nodes', []) if nid in nodes]
        roads.append({
            'id': el['id'], 'highway': hw,
            'oneway': tags.get('oneway', 'no'),
            'name': tags.get('name', ''),
            'lanes': tags.get('lanes', ''),
            'surface': tags.get('surface', ''),
            'nodes': nd,
        })
    return roads


def extract_buildings(elements, nodes):
    buildings = []
    for el in elements:
        if el['type'] != 'way':
            continue
        tags = el.get('tags', {})
        if not tags.get('building'):
            continue
        nd = [{'id': nid, 'lat': nodes[nid][0], 'lon': nodes[nid][1]}
              for nid in el.get('nodes', []) if nid in nodes]
        if len(nd) < 3:
            continue
        levels = 0
        if tags.get('building:levels'):
            try:
                levels = int(tags['building:levels'])
            except ValueError:
                pass
        buildings.append({
            'id': el['id'],
            'building': tags.get('building', 'yes'),
            'levels': levels,
            'height': tags.get('height', ''),
            'name': tags.get('name', ''),
            'amenity': tags.get('amenity', ''),
            'nodes': nd,
        })
    return buildings


def extract_features(elements, nodes):
    """Extract waterways, parks and leisure areas."""
    features = []
    for el in elements:
        if el['type'] != 'way':
            continue
        tags = el.get('tags', {})
        kind = None
        if tags.get('waterway') in ('river', 'stream', 'canal'):
            kind = 'waterway:' + tags['waterway']
        elif tags.get('natural') == 'water':
            kind = 'natural:water'
        elif tags.get('leisure') in ('park', 'recreation_ground', 'garden'):
            kind = 'leisure:' + tags['leisure']
        elif tags.get('landuse') in ('grass', 'recreation_ground', 'park', 'village_green'):
            kind = 'landuse:' + tags['landuse']
        elif tags.get('amenity') == 'parking':
            kind = 'amenity:parking'
        if kind is None:
            continue
        nd = [{'id': nid, 'lat': nodes[nid][0], 'lon': nodes[nid][1]}
              for nid in el.get('nodes', []) if nid in nodes]
        if len(nd) < 2:
            continue
        features.append({
            'id': el['id'],
            'kind': kind,
            'name': tags.get('name', ''),
            'nodes': nd,
        })
    return features


def main():
    s, w, n, e = BBOX
    print(f'Fetching OSM data for bbox: {BBOX}')

    query = f"""
[out:json][timeout:90];
(
  way["highway"]({s},{w},{n},{e});
  way["building"]({s},{w},{n},{e});
  way["waterway"~"river|stream|canal"]({s},{w},{n},{e});
  way["natural"="water"]({s},{w},{n},{e});
  way["leisure"~"park|recreation_ground|garden"]({s},{w},{n},{e});
  way["landuse"~"grass|recreation_ground|park|village_green"]({s},{w},{n},{e});
  way["amenity"="parking"]({s},{w},{n},{e});
);
out body;
>;
out skel qt;
"""
    data = fetch_osm(query, 'all features')
    elements = data.get('elements', [])
    nodes = parse_nodes(elements)

    roads = extract_roads(elements, nodes)
    buildings = extract_buildings(elements, nodes)
    features = extract_features(elements, nodes)

    print(f'  Roads: {len(roads)}, Buildings: {len(buildings)}, Features: {len(features)}')
    print(f'  One-way roads: {sum(1 for r in roads if r["oneway"] in ("yes","1","-1"))}')

    with open(os.path.join(OUT_DIR, 'ballymena_osm_raw.json'), 'w') as f:
        json.dump(data, f)
    with open(os.path.join(OUT_DIR, 'ballymena_roads.json'), 'w') as f:
        json.dump(roads, f, indent=2)
    with open(os.path.join(OUT_DIR, 'ballymena_buildings.json'), 'w') as f:
        json.dump(buildings, f, indent=2)
    with open(os.path.join(OUT_DIR, 'ballymena_features.json'), 'w') as f:
        json.dump(features, f, indent=2)

    hw = Counter(r['highway'] for r in roads)
    print('\n  Highway types:')
    for t, c in hw.most_common():
        print(f'    {t}: {c}')

    feat_kinds = Counter(f['kind'] for f in features)
    if feat_kinds:
        print('\n  Feature kinds:')
        for k, c in feat_kinds.most_common():
            print(f'    {k}: {c}')


if __name__ == '__main__':
    main()
