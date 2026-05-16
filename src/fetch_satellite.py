#!/usr/bin/env python3
"""Download Esri World Imagery tiles for Ballymena BBOX; stitch into satellite.png.

Tiles come from the Esri World Imagery WMTS service (publicly accessible, no key):
  https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}

At ZOOM=17 this gives ~0.69 m/px over the ~2×2 km BBOX (~120 tiles).
Tiles are cached individually so re-runs are fast.
"""
import json, math, os, time, io
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from utils import BBOX

ZOOM = 17
TILE_SIZE = 256
TILE_DELAY = 0.04          # seconds between uncached tile fetches (polite crawl)
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'satellite')

TILE_URL = ('https://server.arcgisonline.com/ArcGIS/rest/services/'
            'World_Imagery/MapServer/tile/{z}/{y}/{x}')
USER_AGENT = 'ballymena-ng-drive/4.2 (educational heritage mapping project)'


# ── Tile-coordinate helpers ──────────────────────────────────────────────────

def deg2tile(lat_deg, lon_deg, zoom):
    """Slippy-map (OSM/Esri XYZ) tile coordinates for a lat/lon at a zoom level."""
    n = 2 ** zoom
    xt = int((lon_deg + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat_deg)
    yt = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return xt, yt


def tile_nw_latlon(xt, yt, zoom):
    """Lat/lon of the north-west (top-left) pixel of a tile."""
    n = 2 ** zoom
    lon = xt / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * yt / n))))
    return lat, lon


# ── Tile fetcher ─────────────────────────────────────────────────────────────

def fetch_tile_bytes(z, yt, xt):
    url = TILE_URL.format(z=z, y=yt, x=xt)
    req = Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urlopen(req, timeout=20) as resp:
            return resp.read()
    except (URLError, HTTPError) as e:
        print(f'    Warning: tile {z}/{yt}/{xt} — {e}')
        return None


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    try:
        from PIL import Image
    except ImportError:
        print('Pillow required — pip install Pillow')
        return

    os.makedirs(OUT_DIR, exist_ok=True)

    s, w, n, e = BBOX
    # Expand one tile-width so crop never clips content at edges
    pad = 0.002

    # Tile range: y0 (north edge) to y1 (south edge); x0 (west) to x1 (east)
    # Note: tile y increases southward, so NW corner has smaller y index
    x0, y0 = deg2tile(n + pad, w - pad, ZOOM)
    x1, y1 = deg2tile(s - pad, e + pad, ZOOM)
    # Clamp so we don't accidentally get reversed ranges
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)

    nx = x1 - x0 + 1
    ny = y1 - y0 + 1
    print(f'Tile grid: {nx}×{ny} = {nx * ny} tiles  (zoom {ZOOM})')

    mosaic = Image.new('RGB', (nx * TILE_SIZE, ny * TILE_SIZE))
    fetched, cached = 0, 0

    for row_i, yt in enumerate(range(y0, y1 + 1)):
        for col_i, xt in enumerate(range(x0, x1 + 1)):
            cache_path = os.path.join(OUT_DIR, f'tile_{ZOOM}_{xt}_{yt}.jpg')
            if os.path.exists(cache_path):
                tile_img = Image.open(cache_path).convert('RGB')
                cached += 1
            else:
                data = fetch_tile_bytes(ZOOM, yt, xt)
                if data:
                    tile_img = Image.open(io.BytesIO(data)).convert('RGB')
                    tile_img.save(cache_path, 'JPEG', quality=92)
                    fetched += 1
                else:
                    tile_img = Image.new('RGB', (TILE_SIZE, TILE_SIZE), (128, 128, 128))
                time.sleep(TILE_DELAY)
            mosaic.paste(tile_img, (col_i * TILE_SIZE, row_i * TILE_SIZE))

        pct = (row_i + 1) / ny * 100
        print(f'  Row {row_i + 1}/{ny}  ({pct:.0f}%)  fetched={fetched} cached={cached}',
              flush=True)

    print(f'Mosaic: {mosaic.size[0]}×{mosaic.size[1]} px  '
          f'(fetched {fetched} new + {cached} cached)')

    # ── Crop to exact BBOX ────────────────────────────────────────────────────
    lat_n_full, lon_w_full = tile_nw_latlon(x0, y0, ZOOM)
    lat_s_full, lon_e_full = tile_nw_latlon(x1 + 1, y1 + 1, ZOOM)

    W, H = mosaic.size

    def lonlat_to_px(lon, lat):
        px = (lon - lon_w_full) / (lon_e_full - lon_w_full) * W
        py = (lat_n_full - lat)  / (lat_n_full - lat_s_full) * H
        return px, py

    left,  top = lonlat_to_px(w, n)
    right, bot = lonlat_to_px(e, s)
    left,  top  = max(0, int(left)),   max(0, int(top))
    right, bot  = min(W, int(right)+1), min(H, int(bot)+1)

    cropped = mosaic.crop((left, top, right, bot))
    cw, ch  = cropped.size
    print(f'Cropped to BBOX: {cw}×{ch} px')

    # Pad to power-of-2 for GPU texture efficiency (nearest ≥ actual size)
    def next_pow2(v):
        p = 1
        while p < v:
            p *= 2
        return p

    tw = next_pow2(cw)
    th = next_pow2(ch)
    if tw != cw or th != ch:
        padded = Image.new('RGB', (tw, th), (0, 0, 0))
        padded.paste(cropped, (0, 0))
        # Store actual pixel extent so build_map.py can compute correct UVs
        crop_w, crop_h = cw, ch
        final_img = padded
        print(f'Padded to {tw}×{th} (power-of-2)')
    else:
        crop_w, crop_h = cw, ch
        final_img = cropped

    out_path = os.path.join(OUT_DIR, 'ballymena_satellite.png')
    final_img.save(out_path, optimize=True)
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f'Saved: {out_path}  ({size_mb:.1f} MB)')

    # ── Geo-reference metadata ────────────────────────────────────────────────
    geo = {
        'bbox':         list(BBOX),
        'zoom':         ZOOM,
        'tex_width':    tw,
        'tex_height':   th,
        'crop_width':   crop_w,
        'crop_height':  crop_h,
    }
    geo_path = os.path.join(OUT_DIR, 'satellite_geo.json')
    with open(geo_path, 'w') as f:
        json.dump(geo, f, indent=2)
    print(f'Geo-reference: {geo_path}')

    # UV crop fractions (the usable portion of the padded texture)
    u_max = crop_w / tw
    v_max = crop_h / th
    print(f'UV crop fraction: u_max={u_max:.4f}  v_max={v_max:.4f}')


if __name__ == '__main__':
    main()
