#!/usr/bin/env python3
"""Ballymena NG Drive — build pipeline entry point.

Usage:
    python run.py fetch     # Download OSM data (roads, buildings, features)
    python run.py dem       # Download SRTM elevation grid (Open-Elevation API)
    python run.py process   # Convert OSM to BeamNG NDJSON (roads, footways, buildings, features)
    python run.py photos    # Validate manifest + generate photo-spot billboards/waypoints
    python run.py build     # Assemble level: terrain + waypoints + packaging
    python run.py all       # Full pipeline: fetch + dem + process + photos + build
"""
import sys, os, subprocess

SRC_DIR = os.path.dirname(os.path.abspath(__file__))

VALID = frozenset(('fetch', 'dem', 'process', 'photos', 'build', 'all'))


def run_script(name):
    path = os.path.join(SRC_DIR, name)
    print(f"\n{'='*60}", flush=True)
    print(f"Running: {name}", flush=True)
    print(f"{'='*60}", flush=True)
    result = subprocess.run([sys.executable, path], cwd=SRC_DIR)
    if result.returncode != 0:
        print(f"  FAILED (exit {result.returncode})")
        sys.exit(result.returncode)


def main():
    cmds = sys.argv[1:] if len(sys.argv) > 1 else ['all']
    for cmd in cmds:
        if cmd not in VALID:
            print(f"Unknown command: {cmd}")
            print(f"Usage: python run.py [{' | '.join(sorted(VALID))}]")
            sys.exit(1)
        if cmd in ('fetch', 'all'):
            run_script('fetch_osm.py')
        if cmd in ('dem', 'all'):
            run_script('fetch_dem.py')
        if cmd in ('process', 'all'):
            run_script('parse_roads.py')
            run_script('parse_footways.py')
            run_script('parse_buildings.py')
            run_script('parse_features.py')
            run_script('gen_waypoints.py')
        if cmd in ('photos', 'all'):
            run_script('validate_photos.py')
            run_script('gen_photo_spots.py')
        if cmd in ('build', 'all'):
            run_script('build_map.py')


if __name__ == '__main__':
    main()
