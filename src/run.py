#!/usr/bin/env python3
"""Ballymena NG Drive — build pipeline entry point.

Usage:
    python run.py fetch     # Download OSM data (roads, buildings, features)
    python run.py dem       # Download SRTM elevation grid (Open-Elevation API)
    python run.py process   # Convert OSM data to BeamNG NDJSON
    python run.py build     # Generate terrain + level files
    python run.py all       # Full pipeline: fetch + dem + process + build
"""
import sys, os, subprocess

SRC_DIR = os.path.dirname(os.path.abspath(__file__))


def run_script(name):
    path = os.path.join(SRC_DIR, name)
    print(f"\n{'='*60}", flush=True)
    print(f"Running: {name}", flush=True)
    print(f"{'='*60}", flush=True)
    result = subprocess.run([sys.executable, path], cwd=SRC_DIR)
    if result.returncode != 0:
        print(f"  FAILED with code {result.returncode}")
        sys.exit(result.returncode)


VALID = ('fetch', 'dem', 'process', 'build', 'all')


def main():
    cmds = sys.argv[1:] if len(sys.argv) > 1 else ['all']
    for cmd in cmds:
        if cmd not in VALID:
            print(f"Unknown command: {cmd}")
            print(f"Usage: python run.py [{' | '.join(VALID)}]")
            sys.exit(1)
        if cmd in ('fetch', 'all'):
            run_script('fetch_osm.py')
        if cmd in ('dem', 'all'):
            run_script('fetch_dem.py')
        if cmd in ('process', 'all'):
            run_script('parse_roads.py')
            run_script('parse_buildings.py')
        if cmd in ('build', 'all'):
            run_script('build_map.py')


if __name__ == '__main__':
    main()
