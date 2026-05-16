#!/usr/bin/env python3
"""Generate photo-spot billboards and waypoints from photo_manifest.json.

For each manifest entry within the BBOX:
  1. Convert lat/lon to local metres
  2. Sample DEM for ground Z
  3. Generate 1024×384 composite "then/now" PNG (Pillow) — placeholder if images absent
  4. Emit a TSStatic billboard panel at the location
  5. Emit a BeamNGWaypoint named 'photo_<id>' (triggers Lua overlay)

Output: output/photo_spots.ndjson
Textures: output/levels/ballymena/art/textures/photo_spots/<id>.png
"""
import json, os, uuid, math

from utils import latlon_to_meters, get_bbox_meters, sample_dem

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(BASE_DIR, 'data', 'photos', 'photo_manifest.json')
IMAGES_DIR    = os.path.join(BASE_DIR, 'data', 'photos')
OUT_DIR       = os.path.join(BASE_DIR, 'output')
DEM_PATH      = os.path.join(BASE_DIR, 'data', 'dem', 'elevation_grid.json')

BILLBOARD_W   = 4.0    # metres
BILLBOARD_H   = 3.0    # metres
PANEL_DEPTH   = 0.08   # metres (thin slab)
COMPOSITE_W   = 1024   # px
COMPOSITE_H   = 384    # px
WP_RADIUS     = 8.0    # metres — waypoint trigger radius


def load_manifest():
    if not os.path.exists(MANIFEST_PATH):
        print('  No photo_manifest.json — skipping photo spots')
        return []
    with open(MANIFEST_PATH) as f:
        return json.load(f).get('photos', [])


def load_dem():
    if not os.path.exists(DEM_PATH):
        return None
    with open(DEM_PATH) as f:
        return json.load(f)


def heading_to_rotation_matrix(heading_deg):
    """Compass heading (CW from north) → 3×3 Z-rotation matrix, row-major flat list.

    Billboard plane.dae has normal +Y (faces north). Rotating by -H maps that
    normal to face in the compass direction H.
    """
    theta = -math.radians(heading_deg)
    c = round(math.cos(theta), 6)
    s = round(math.sin(theta), 6)
    return [c, -s, 0,
            s,  c, 0,
            0,  0, 1]


def _open_image(rel_path):
    """Load an image from data/photos/<rel_path>. Returns PIL Image or None."""
    try:
        from PIL import Image
        full = os.path.join(IMAGES_DIR, rel_path)
        if os.path.exists(full):
            return Image.open(full).convert('RGB')
    except Exception:
        pass
    return None


def make_composite(photo, out_path):
    """Write 1024×384 then/now composite PNG. Generates placeholder if images absent."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    W, H = COMPOSITE_W, COMPOSITE_H
    half = W // 2

    img_then = _open_image(photo.get('image_then', '')) if photo.get('image_then') else None
    img_now  = _open_image(photo.get('image_now',  '')) if photo.get('image_now')  else None

    canvas = Image.new('RGB', (W, H), (15, 15, 15))
    draw   = ImageDraw.Draw(canvas)

    year_then = photo.get('year_then', '?')
    year_now  = photo.get('year_now') or 'Now'
    desc      = (photo.get('description') or photo.get('id', ''))[:80]

    def paste_panel(src, box_x, box_w, label, credit):
        label_h = 26
        photo_h = H - label_h - 24  # reserve top bar too
        if src:
            thumb = src.resize((box_w - 4, photo_h), Image.LANCZOS)
            canvas.paste(thumb, (box_x + 2, 24))
        else:
            draw.rectangle([box_x, 24, box_x + box_w - 1, H - label_h - 1],
                           fill=(30, 30, 30))
            tw = 'Photo wanted'
            draw.text((box_x + box_w // 2 - 48, H // 2 - 20), tw, fill=(100, 100, 100))
            draw.text((box_x + box_w // 2 - 72, H // 2),
                      'github.com/ballymena-ng-drive', fill=(70, 70, 70))
        # Label bar
        draw.rectangle([box_x, H - label_h, box_x + box_w - 1, H - 1], fill=(0, 0, 0))
        draw.text((box_x + 6, H - label_h + 4), label, fill=(220, 220, 220))
        if credit:
            draw.text((box_x + 6, H - 12), f'© {credit[:40]}', fill=(120, 120, 120))

    paste_panel(img_then, 0,      half - 1, f'Then  c.{year_then}',
                photo.get('credit_then', ''))
    paste_panel(img_now,  half + 1, half - 1, f'Now  {year_now}',
                photo.get('credit_now', ''))

    # Dividing line
    draw.line([(half, 0), (half, H)], fill=(255, 190, 0), width=2)

    # Top caption bar
    draw.rectangle([0, 0, W, 22], fill=(0, 0, 0))
    draw.text((6, 4), desc, fill=(240, 240, 240))

    canvas.save(out_path, 'PNG', optimize=False)
    return True


def make_billboard_tsstatic(photo_id, x, y, z, heading):
    rot = heading_to_rotation_matrix(heading)
    return {
        'class': 'TSStatic',
        'name': f'photo_panel_{photo_id}',
        'persistentId': str(uuid.uuid4()),
        '__parent': 'PhotoSpots',
        'position': [round(x, 2), round(y, 2), round(z + BILLBOARD_H / 2, 2)],
        'scale': [BILLBOARD_W, PANEL_DEPTH, BILLBOARD_H],
        'rotationMatrix': rot,
        'shapeName': '/levels/ballymena/art/shapes/billboard/plane.dae',
    }


def make_photo_waypoint(photo_id, x, y, z, desc):
    return {
        'class': 'BeamNGWaypoint',
        'name': f'photo_{photo_id}',
        'persistentId': str(uuid.uuid4()),
        '__parent': 'PhotoSpots',
        'position': [round(x, 2), round(y, 2), round(z + 0.1, 2)],
        'radius': WP_RADIUS,
        'normalRadius': WP_RADIUS,
        'description': desc,
    }


def generate_photo_spots(photos, dem, base_elev, tex_dir):
    """Return flat list of level objects (TSStatic panels + waypoints)."""
    x_min, x_max, y_min, y_max = get_bbox_meters()
    objects = []
    generated = []

    for photo in photos:
        pid = photo.get('id', '')
        if not pid:
            continue

        lat, lon = photo.get('lat', 0.0), photo.get('lon', 0.0)
        x, y = latlon_to_meters(lat, lon)

        if not (x_min <= x <= x_max and y_min <= y <= y_max):
            continue

        z = max(0.0, sample_dem(dem, x, y) - base_elev) if dem else 0.0
        heading = photo.get('heading', 0)
        desc    = photo.get('description', '')

        # Composite PNG
        tex_out = os.path.join(tex_dir, f'{pid}.png')
        make_composite(photo, tex_out)

        objects.append(make_billboard_tsstatic(pid, x, y, z, heading))
        objects.append(make_photo_waypoint(pid, x, y, z, desc))
        generated.append(pid)

    return objects, generated


def main():
    photos    = load_manifest()
    dem       = load_dem()
    base_elev = dem['min_elev'] - 2.0 if dem else 0.0

    print(f'Processing {len(photos)} photo manifest entries …')

    tex_dir = os.path.join(OUT_DIR, 'levels', 'ballymena',
                           'art', 'textures', 'photo_spots')
    os.makedirs(tex_dir, exist_ok=True)

    objects, generated = generate_photo_spots(photos, dem, base_elev, tex_dir)

    out_path = os.path.join(OUT_DIR, 'photo_spots.ndjson')
    with open(out_path, 'w') as f:
        for obj in objects:
            f.write(json.dumps(obj, separators=(',', ':')) + '\n')

    spots = len(generated)
    print(f'  Generated {spots} photo spot(s) ({spots * 2} objects) → {out_path}')
    for pid in generated:
        photo = next(p for p in photos if p['id'] == pid)
        has_then = bool(photo.get('image_then') and
                        os.path.exists(os.path.join(IMAGES_DIR, photo['image_then'])))
        has_now  = bool(photo.get('image_now') and
                        os.path.exists(os.path.join(IMAGES_DIR, photo['image_now'])))
        status = ('✓✓' if has_then and has_now else
                  '✓·' if has_then else
                  '··')
        print(f'    {status} {pid}')
    if spots:
        have = sum(1 for pid in generated
                   for p in photos if p['id'] == pid and p.get('image_then') and
                   os.path.exists(os.path.join(IMAGES_DIR, p['image_then'])))
        print(f'  Images present: {have}/{spots} "then" photos '
              f'({spots - have} placeholder(s) — please contribute!)')


if __name__ == '__main__':
    main()
