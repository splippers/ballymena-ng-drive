#!/usr/bin/env python3
"""Fetch SRTM elevation grid for Ballymena BBOX via Open-Elevation API.

Saves data/dem/elevation_grid.json — a 64×64 lat/lon grid of AMSL elevations
that build_map.py uses to generate a real terrain heightmap.
"""
import json, urllib.request, urllib.error, time, os
from utils import BBOX

GRID_ROWS = 96
GRID_COLS = 96
BATCH_SIZE = 100
API_URL = 'https://api.open-elevation.com/api/v1/lookup'

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'dem')
os.makedirs(DATA_DIR, exist_ok=True)


def build_grid():
    s, w, n, e = BBOX
    pts = []
    for row in range(GRID_ROWS):
        lat = s + (n - s) * row / (GRID_ROWS - 1)
        for col in range(GRID_COLS):
            lon = w + (e - w) * col / (GRID_COLS - 1)
            pts.append({'latitude': round(lat, 6), 'longitude': round(lon, 6)})
    return pts


def fetch_elevations(points):
    elevations = []
    n_batches = (len(points) + BATCH_SIZE - 1) // BATCH_SIZE
    for bi, start in enumerate(range(0, len(points), BATCH_SIZE)):
        batch = points[start:start + BATCH_SIZE]
        body = json.dumps({'locations': batch}).encode()
        success = False
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    API_URL, data=body,
                    headers={'Content-Type': 'application/json',
                             'User-Agent': 'ballymena-ng-drive/0.1'})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                results = data['results']
                elevations.extend(r['elevation'] for r in results)
                lo = min(r['elevation'] for r in results)
                hi = max(r['elevation'] for r in results)
                print(f'  Batch {bi+1}/{n_batches}: {len(batch)} pts, {lo:.0f}–{hi:.0f} m')
                success = True
                break
            except Exception as exc:
                print(f'    attempt {attempt+1} failed: {exc}')
                if attempt < 2:
                    time.sleep(3)
        if not success:
            print(f'  WARNING: batch {bi+1} failed — using 60 m fallback')
            elevations.extend([60.0] * len(batch))
        if bi < n_batches - 1:
            time.sleep(0.4)
    return elevations


def main():
    out_path = os.path.join(DATA_DIR, 'elevation_grid.json')
    points = build_grid()
    print(f'Fetching {len(points)} elevation samples ({GRID_ROWS}×{GRID_COLS} grid) …')
    elevs = fetch_elevations(points)

    grid = [elevs[r * GRID_COLS:(r + 1) * GRID_COLS] for r in range(GRID_ROWS)]
    flat = [v for row in grid for v in row]
    result = {
        'bbox': BBOX,
        'rows': GRID_ROWS,
        'cols': GRID_COLS,
        'grid': grid,
        'min_elev': min(flat),
        'max_elev': max(flat),
    }
    with open(out_path, 'w') as f:
        json.dump(result, f)
    print(f'Saved: {out_path}')
    print(f'Elevation range: {result["min_elev"]:.1f}–{result["max_elev"]:.1f} m AMSL')


if __name__ == '__main__':
    main()
