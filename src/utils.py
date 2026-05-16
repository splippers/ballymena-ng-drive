import math

CENTER_LAT = 54.864
CENTER_LON = -6.278

LAT_SCALE = 111320.0
LON_SCALE = 111320.0 * math.cos(math.radians(CENTER_LAT))

# OSM bounding box for Ballymena town centre (south, west, north, east)
BBOX = (54.856, -6.293, 54.874, -6.262)


def latlon_to_meters(lat, lon):
    """Equirectangular projection — accurate for the small town-centre area."""
    return ((lon - CENTER_LON) * LON_SCALE, (lat - CENTER_LAT) * LAT_SCALE)


def meters_to_latlon(x, y):
    return (CENTER_LAT + y / LAT_SCALE, CENTER_LON + x / LON_SCALE)


def get_bbox_meters():
    """Return (x_min, x_max, y_min, y_max) in local metres for BBOX."""
    s, w, n, e = BBOX
    x_min = (w - CENTER_LON) * LON_SCALE
    x_max = (e - CENTER_LON) * LON_SCALE
    y_min = (s - CENTER_LAT) * LAT_SCALE
    y_max = (n - CENTER_LAT) * LAT_SCALE
    return x_min, x_max, y_min, y_max


def road_width(highway_tag, lanes_str=None):
    """Estimate road half-width in metres based on OSM highway tag."""
    widths = {
        'motorway': 12, 'motorway_link': 8,
        'trunk': 10, 'trunk_link': 7,
        'primary': 8, 'primary_link': 6,
        'secondary': 7, 'secondary_link': 5.5,
        'tertiary': 6, 'tertiary_link': 5,
        'unclassified': 5,
        'residential': 5,
        'living_street': 4,
        'service': 3.5,
        'pedestrian': 5,
    }
    if lanes_str:
        try:
            return int(lanes_str) * 3.5
        except ValueError:
            pass
    return widths.get(highway_tag, 5.0)


# ── Liang-Barsky line clipping ──────────────────────────────────────────────

def _clip_line(x1, y1, x2, y2, xmin, xmax, ymin, ymax):
    """Liang-Barsky clip. Returns (cx1, cy1, cx2, cy2) or None if fully outside."""
    dx, dy = x2 - x1, y2 - y1
    ps = (-dx, dx, -dy, dy)
    qs = (x1 - xmin, xmax - x1, y1 - ymin, ymax - y1)
    t0, t1 = 0.0, 1.0
    for p, q in zip(ps, qs):
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            t0 = max(t0, q / p)
        else:
            t1 = min(t1, q / p)
    if t0 > t1:
        return None
    return (x1 + t0 * dx, y1 + t0 * dy, x1 + t1 * dx, y1 + t1 * dy)


def clip_polyline(pts, xmin, xmax, ymin, ymax):
    """Clip a polyline to an axis-aligned bbox.
    Returns a list of clipped sub-polylines (splitting at bbox crossings)."""
    if len(pts) < 2:
        return [list(pts)] if pts else []
    segments = []
    current = None
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        clipped = _clip_line(x1, y1, x2, y2, xmin, xmax, ymin, ymax)
        if clipped is None:
            if current:
                segments.append(current)
                current = None
            continue
        cx1, cy1, cx2, cy2 = clipped
        if current is None:
            current = [(cx1, cy1), (cx2, cy2)]
        else:
            last = current[-1]
            if abs(last[0] - cx1) < 0.001 and abs(last[1] - cy1) < 0.001:
                current.append((cx2, cy2))
            else:
                segments.append(current)
                current = [(cx1, cy1), (cx2, cy2)]
    if current:
        segments.append(current)
    return segments


# ── Bilinear DEM interpolation ───────────────────────────────────────────────

def _bilinear(grid, rows, cols, r, c):
    r = max(0.0, min(rows - 1, r))
    c = max(0.0, min(cols - 1, c))
    r0, c0 = int(r), int(c)
    r1 = min(r0 + 1, rows - 1)
    c1 = min(c0 + 1, cols - 1)
    dr, dc = r - r0, c - c0
    return (grid[r0][c0] * (1 - dr) * (1 - dc) +
            grid[r0][c1] * (1 - dr) * dc +
            grid[r1][c0] * dr * (1 - dc) +
            grid[r1][c1] * dr * dc)


def sample_dem(dem_data, local_x, local_y):
    """Return elevation (m AMSL) at local-metre XY by bilinear interpolation."""
    s, w, n, e = dem_data['bbox']
    rows, cols = dem_data['rows'], dem_data['cols']
    grid = dem_data['grid']
    lat, lon = meters_to_latlon(local_x, local_y)
    r = (lat - s) / (n - s) * (rows - 1)
    c = (lon - w) / (e - w) * (cols - 1)
    return _bilinear(grid, rows, cols, r, c)
