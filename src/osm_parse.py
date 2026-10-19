#!/usr/bin/env python3
"""Minimal OSM road parser for the game-elements layer.

Companion to the shared ``tools/osm_parse.py`` used by the felsted-ng-drive and
maldon-ng-drive pipelines: the same idea reduced to the road subset the
Ballymena pipeline needs.  Reads the raw Overpass cache written by fetch_osm.py
(``data/osm/ballymena_osm_raw.json``), which retains every OSM tag.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'osm')
OSM_RAW = os.path.join(DATA_DIR, 'ballymena_osm_raw.json')

# Width lookup for highway types (metres) — matches tools/osm_parse.py
HIGHWAY_WIDTH = {
    'motorway': 12.0, 'trunk': 9.0, 'primary': 7.5,
    'secondary': 6.5, 'tertiary': 5.5, 'unclassified': 5.0,
    'residential': 4.5, 'living_street': 4.0, 'service': 3.5,
    'track': 3.0, 'bridleway': 2.5, 'cycleway': 2.0,
    'footway': 2.0, 'path': 1.5, 'pedestrian': 3.0,
    'steps': 1.5,
}

HIGHWAY_MATERIAL = {
    'motorway': 'road_rubber_sticky', 'trunk': 'road_rubber_sticky',
    'primary': 'road_rubber_sticky', 'secondary': 'road_rubber_sticky',
    'tertiary': 'road_rubber_sticky', 'unclassified': 'road_rubber_sticky',
    'residential': 'road_rubber_sticky', 'living_street': 'road_rubber_sticky',
    'service': 'road_rubber_sticky', 'track': 'dirt',
    'bridleway': 'dirt', 'cycleway': 'sidewalk',
    'footway': 'sidewalk', 'path': 'sidewalk',
    'pedestrian': 'sidewalk', 'steps': 'sidewalk',
}

_SKIP = {'proposed', 'construction', 'platform'}


@dataclass
class OsmRoad:
    osm_id:    int
    name:      str
    hw_type:   str
    width:     float
    material:  str
    gps_nodes: list                       # (lat, lon)
    tags:      dict = field(default_factory=dict)   # full OSM tags


def _width(tags: dict, hw: str) -> float:
    """Best-effort numeric width — OSM values can be '3', '3.5 m', '3;4' …"""
    raw = tags.get('width')
    if raw:
        try:
            return float(str(raw).split(';')[0].split()[0].rstrip('m').strip())
        except (ValueError, IndexError):
            pass
    return HIGHWAY_WIDTH.get(hw, 4.0)


def load_roads(path: str | None = None) -> list[OsmRoad]:
    """Parse every highway way in the cached Overpass JSON into OsmRoad."""
    p = path or OSM_RAW
    if not os.path.exists(p):
        log.warning('OSM cache not found at %s; no game elements.', p)
        return []

    with open(p, encoding='utf-8') as f:
        raw = json.load(f)

    nodes_by_id = {e['id']: (e['lat'], e['lon'])
                   for e in raw['elements'] if e['type'] == 'node'}

    roads: list[OsmRoad] = []
    seen: set[int] = set()
    for el in raw['elements']:
        if el['type'] != 'way':
            continue
        wid = el['id']
        if wid in seen:
            continue
        seen.add(wid)

        tags = el.get('tags', {})
        if 'highway' not in tags:
            continue
        hw = tags['highway']
        if hw in _SKIP:
            continue
        gps = [nodes_by_id[n] for n in el['nodes'] if n in nodes_by_id]
        if len(gps) < 2:
            continue

        roads.append(OsmRoad(
            osm_id   = wid,
            name     = tags.get('name', f'road_{wid}'),
            hw_type  = hw,
            width    = _width(tags, hw),
            material = HIGHWAY_MATERIAL.get(hw, 'road_rubber_sticky'),
            gps_nodes= gps,
            tags     = dict(tags),
        ))

    log.info('OSM: %d highway ways', len(roads))
    return roads
