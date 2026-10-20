#!/usr/bin/env python3
"""Fetch high-resolution Northern Ireland LiDAR terrain for the Ballymena BBOX.

Source
──────
OSNI / Land & Property Services "River Basin LiDAR 2010" — the Ballymena
1 m DTM, flown 23/04/2009, licensed under the Open Government Licence and
published on Open Data NI.  The same data is mirrored as a cloud-optimised
GeoTIFF (Zstandard, float32, 1 m, EPSG:29902 TM65 / Irish Grid) which we can
stream tile-by-tile with HTTP range requests — no 130 MB download.

England's maps use the Defra/EA WCS (tools/lidar.py in the sibling repos);
Northern Ireland has no equivalent coverage service, so this is the NI
counterpart.  See README.

Output
──────
data/dem/elevation_grid_lidar.json — the SAME schema as fetch_dem.py
(bbox / rows / cols / grid / min_elev / max_elev), just at 1 m source
resolution, so build_map.py reads it unchanged.  build_map.load_dem()
prefers this file and falls back to data/dem/elevation_grid.json (SRTM).

Attribution: Contains OSNI LiDAR data © Crown copyright 2010, reproduced with
the permission of Land & Property Services under the Open Government Licence.
"""
import json
import math
import os
import struct
import time
import urllib.request

import numpy as np
import zstandard
from pyproj import Transformer

from utils import BBOX

COG_URL = ('https://data.better-open-data.com/lidar_zstd/'
           'Ballymena_23_04_2009_DTM.tif')
LIDAR_EPSG = 29902          # TM65 / Irish Grid, read from the GeoTIFF GeoKeys
SURVEY_DATE = '2009-04-23'
GRID_ROWS = 1025
GRID_COLS = 1025
NODATA = -9999.0

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'dem')
UA = {'User-Agent': 'ballymena-ng-drive/0.2 (+https://github.com/splippers)'}


# ── HTTP range reads ─────────────────────────────────────────────────────────

def http_range(url, start, end, retries=4):
    """Read bytes [start, end] of a remote file (inclusive)."""
    req = urllib.request.Request(
        url, headers={**UA, 'Range': f'bytes={start}-{end}'})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except Exception as exc:                       # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'failed to fetch {url} [{start}-{end}]: {last}')


# ── GeoTIFF index ────────────────────────────────────────────────────────────

def read_tiff_index(url):
    """Parse the COG's IFD from the first 16 KB → geometry + tile index."""
    buf = http_range(url, 0, 16383)
    if buf[:2] not in (b'II', b'MM'):
        raise RuntimeError('not a TIFF')
    endian = '<' if buf[:2] == b'II' else '>'
    ifd = struct.unpack(endian + 'I', buf[4:8])[0]
    n = struct.unpack(endian + 'H', buf[ifd:ifd + 2])[0]

    tags = {}
    for i in range(n):
        o = ifd + 2 + i * 12
        tag, typ, cnt = struct.unpack(endian + 'HHI', buf[o:o + 8])
        tags[tag] = (typ, cnt, struct.unpack(endian + 'I', buf[o + 8:o + 12])[0])

    def doubles(tag):
        _, cnt, off = tags[tag]
        return struct.unpack(endian + str(cnt) + 'd', buf[off:off + 8 * cnt])

    def u32array(tag):
        _, cnt, off = tags[tag]
        return np.frombuffer(buf[off:off + 4 * cnt], dtype='<u4' if endian == '<' else '>u4')

    scale = doubles(33550)
    tie = doubles(33922)
    return {
        'width':       tags[256][2],
        'height':      tags[257][2],
        'tile_w':      tags[322][2],
        'tile_h':      tags[323][2],
        'compression': tags[259][2],
        'predictor':   tags[317][2],
        'bits':        tags[258][2],
        'origin_e':    tie[3],
        'origin_n':    tie[4],
        'pixel':       scale[0],
        'offsets':     u32array(324),
        'counts':      u32array(325),
    }


def _decode_tile(idx, meta, url, zdec):
    """Fetch one tile, Zstd-decompress, undo the horizontal predictor."""
    off = int(meta['offsets'][idx])
    cnt = int(meta['counts'][idx])
    raw = zdec.decompress(http_range(url, off, off + cnt - 1),
                          max_output_size=meta['tile_w'] * meta['tile_h'] * 4)
    arr = np.frombuffer(raw, dtype='<u4').reshape(meta['tile_h'], meta['tile_w'])
    if meta['predictor'] == 2:                      # horizontal differencing
        arr = np.cumsum(arr, axis=1, dtype=np.uint32)
    return arr.view('<f4')


def read_projected_window(meta, url, zdec, e0, e1, n0, n1):
    """Return the LiDAR window covering a projected (EPSG:29902) box.

    Row 0 is the north edge, column 0 the west edge; values in metres AMSL,
    with NODATA → NaN.
    """
    tw, th = meta['tile_w'], meta['tile_h']
    across = (meta['width'] + tw - 1) // tw
    c0 = max(0, int(math.floor(e0 - meta['origin_e'])))
    c1 = min(meta['width'] - 1, int(math.ceil(e1 - meta['origin_e'])))
    r0 = max(0, int(math.floor(meta['origin_n'] - n1)))
    r1 = min(meta['height'] - 1, int(math.ceil(meta['origin_n'] - n0)))

    out = np.full((r1 - r0 + 1, c1 - c0 + 1), np.nan, dtype=np.float32)
    tiles = 0
    for ty in range(r0 // th, r1 // th + 1):
        for tx in range(c0 // tw, c1 // tw + 1):
            tile = _decode_tile(ty * across + tx, meta, url, zdec)
            tiles += 1
            py0, px0 = ty * th, tx * tw
            sy0, sy1 = max(py0, r0), min(py0 + th - 1, r1) + 1
            sx0, sx1 = max(px0, c0), min(px0 + tw - 1, c1) + 1
            if sy1 > sy0 and sx1 > sx0:
                sub = tile[sy0 - py0:sy1 - py0, sx0 - px0:sx1 - px0]
                out[sy0 - r0:sy1 - r0, sx0 - c0:sx1 - c0] = np.where(
                    sub <= NODATA + 1.0, np.nan, sub)
    print(f'  decoded {tiles} LiDAR tiles ({out.shape[0]}x{out.shape[1]} px)')
    return out, {'e0': meta['origin_e'] + c0,
                 'n1': meta['origin_n'] - r0,
                 'pixel': meta['pixel']}


# ── Resample onto the map's lat/lon grid ─────────────────────────────────────

def _bilinear(filled, fr, fc):
    r0 = np.clip(np.floor(fr).astype(int), 0, filled.shape[0] - 1)
    c0 = np.clip(np.floor(fc).astype(int), 0, filled.shape[1] - 1)
    r1 = np.clip(r0 + 1, 0, filled.shape[0] - 1)
    c1 = np.clip(c0 + 1, 0, filled.shape[1] - 1)
    dr = np.clip(fr - r0, 0.0, 1.0)
    dc = np.clip(fc - c0, 0.0, 1.0)
    return (filled[r0, c0] * (1 - dr) * (1 - dc) +
            filled[r0, c1] * (1 - dr) * dc +
            filled[r1, c0] * dr * (1 - dc) +
            filled[r1, c1] * dr * dc)


def resample_to_bbox(window, wmeta, rows, cols):
    """Sample the LiDAR window onto a rows x cols lat/lon grid over BBOX."""
    s, w, n, e = BBOX
    lats = np.linspace(s, n, rows)
    lons = np.linspace(w, e, cols)
    lon_g, lat_g = np.meshgrid(lons, lats)

    tr = Transformer.from_crs(4326, LIDAR_EPSG, always_xy=True)
    east, north = tr.transform(lon_g, lat_g)

    fc = (east - wmeta['e0']) / wmeta['pixel']
    fr = (wmeta['n1'] - north) / wmeta['pixel']

    filled = window.copy()
    nan_mask = np.isnan(filled)
    if nan_mask.any():
        fill = float(np.nanmean(filled)) if (~nan_mask).any() else 0.0
        print(f'  filling {nan_mask.mean()*100:.1f}% nodata gaps with {fill:.1f} m')
        filled[nan_mask] = fill

    return _bilinear(filled, fr, fc)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, 'elevation_grid_lidar.json')

    print(f'Reading LiDAR index: {COG_URL}')
    meta = read_tiff_index(COG_URL)
    print(f'  {meta["width"]}x{meta["height"]} px, {meta["pixel"]:g} m, '
          f'tile {meta["tile_w"]}x{meta["tile_h"]}, '
          f'compression {meta["compression"]} (Zstd)')

    # BBOX corners → EPSG:29902, so we only decode the intersecting tiles.
    tr = Transformer.from_crs(4326, LIDAR_EPSG, always_xy=True)
    s, w, n, e = BBOX
    corners = [(w, s), (e, s), (w, n), (e, n), (w, (s + n) / 2),
               (e, (s + n) / 2), ((w + e) / 2, s), ((w + e) / 2, n)]
    pts = [tr.transform(lon, lat) for lon, lat in corners]
    e_vals = [p[0] for p in pts]
    n_vals = [p[1] for p in pts]

    zdec = zstandard.ZstdDecompressor()
    window, wmeta = read_projected_window(
        meta, COG_URL, zdec, min(e_vals), max(e_vals), min(n_vals), max(n_vals))

    grid_arr = resample_to_bbox(window, wmeta, GRID_ROWS, GRID_COLS)

    grid = [[round(float(v), 2) for v in row] for row in grid_arr]
    flat = [v for row in grid for v in row]
    result = {
        'source':      'OSNI River Basin LiDAR 2010 — Ballymena 1 m DTM',
        'survey_date': SURVEY_DATE,
        'resolution_m': meta['pixel'],
        'crs':         f'EPSG:{LIDAR_EPSG}',
        'attribution': ('Contains OSNI LiDAR data © Crown copyright 2010, '
                        'reproduced under the Open Government Licence.'),
        'bbox':        BBOX,
        'rows':        GRID_ROWS,
        'cols':        GRID_COLS,
        'grid':        grid,
        'min_elev':    min(flat),
        'max_elev':    max(flat),
    }
    with open(out_path, 'w') as f:
        json.dump(result, f, separators=(',', ':'))

    print(f'Saved: {out_path}  ({os.path.getsize(out_path)//1024} KB)')
    print(f'Elevation range: {result["min_elev"]:.1f}–{result["max_elev"]:.1f} m AMSL '
          f'({GRID_ROWS}x{GRID_COLS} grid)')


if __name__ == '__main__':
    main()
