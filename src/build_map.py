#!/usr/bin/env python3
"""Build the Ballymena BeamNG level — v4.2.

New in v4.2:
• Satellite ground-plane: Esri World Imagery aerial photo applied as a
  textured TSStatic quad covering the full level area.  Run
  "python run.py satellite" to fetch tiles first; build_map.py then
  embeds the texture and generates a UV-correct satellite_plane.dae.
• Photo spots (v4.0): billboard panels + Then & Now Lua overlay.
• Typed building shapes (v4.1): pitched-roof / flat-roof variants.
"""
import json, os, struct, uuid, shutil
from gen_box_dae import generate_unit_box_dae
from gen_billboard_dae import generate_billboard_dae
from gen_building_shapes import generate_all_shapes
from gen_sat_plane_dae import generate_sat_plane_dae
from utils import get_bbox_meters, sample_dem

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, 'output')
LEVEL_DIR = os.path.join(OUT_DIR, 'levels', 'ballymena')
DEM_PATH = os.path.join(BASE_DIR, 'data', 'dem', 'elevation_grid.json')

TERRAIN_FILENAME = 'ballymena.ter'
MAX_HEIGHT = 120
MIN_LEVEL_SIZE = 1024
MAX_LEVEL_SIZE = 8192
BOUNDS_MARGIN = 1.18

VERSION = '4.2.0'

PHOTO_MANIFEST_SRC = os.path.join(BASE_DIR, 'data', 'photos', 'photo_manifest.json')
LUA_SCRIPT_SRC     = os.path.join(BASE_DIR, 'scripts', 'photo_spots.lua')
SAT_PNG_SRC        = os.path.join(BASE_DIR, 'data', 'satellite', 'ballymena_satellite.png')
SAT_GEO_SRC        = os.path.join(BASE_DIR, 'data', 'satellite', 'satellite_geo.json')


# ── I/O helpers ─────────────────────────────────────────────────────────────

def write_items_level(path, objects):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for obj in objects:
            f.write(json.dumps(obj, separators=(',', ':')) + '\n')


def new_pid():
    return str(uuid.uuid4())


def load_ndjson(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def load_dem():
    if not os.path.exists(DEM_PATH):
        return None
    with open(DEM_PATH) as f:
        return json.load(f)


def load_satellite_geo():
    """Return satellite geo-reference dict, or None if not yet fetched."""
    if not os.path.exists(SAT_GEO_SRC):
        return None
    with open(SAT_GEO_SRC) as f:
        return json.load(f)


def make_satellite_ground_plane(level_size, u_max, v_max, base_elev):
    """Return TSStatic object for the satellite ground plane."""
    return {
        'name': 'satellite_ground',
        'class': 'TSStatic',
        'persistentId': new_pid(),
        '__parent': 'MissionGroup',
        'position': [0.0, 0.0, round(base_elev - 0.3, 2)],
        'shapeName': '/levels/ballymena/art/shapes/terrain/satellite_plane.dae',
        'scale': [round(float(level_size), 1),
                  round(float(level_size), 1), 1.0],
        'rotationMatrix': [1, 0, 0, 0, 1, 0, 0, 0, 1],
        'useInstanceRenderData': False,
        'annotation': 'TERRAIN',
    }


# ── Terrain sizing ───────────────────────────────────────────────────────────

def bounds_from_ndjson(roads, buildings):
    xs, ys = [], []
    for r in roads:
        for n in r.get('nodes', []):
            if len(n) >= 2:
                xs.append(float(n[0])); ys.append(float(n[1]))
    for b in buildings:
        pos = b.get('position')
        if pos and len(pos) >= 2:
            xs.append(float(pos[0])); ys.append(float(pos[1]))
    return (min(xs), max(xs), min(ys), max(ys)) if xs else None


def pick_level_size(min_x, max_x, min_y, max_y):
    half = max(abs(min_x), abs(max_x), abs(min_y), abs(max_y))
    need = 2.0 * half * BOUNDS_MARGIN
    size = MIN_LEVEL_SIZE
    while size < need and size < MAX_LEVEL_SIZE:
        size *= 2
    return min(max(size, MIN_LEVEL_SIZE), MAX_LEVEL_SIZE)


def pick_terrain_res(level_size):
    return min(4096, max(1024, min(level_size, 4096)))


# ── Elevation ────────────────────────────────────────────────────────────────

def build_elevation_array(dem, terrain_size, base_elev):
    """Uint16 heightmap via PIL bilinear resize; falls back to pure Python."""
    if dem is None:
        return [0] * (terrain_size * terrain_size)
    try:
        from PIL import Image
        rows, cols = dem['rows'], dem['cols']
        grid = dem['grid']
        pil_data = [min(65535, max(0, int((grid[r][c] - base_elev) / MAX_HEIGHT * 65535)))
                    for r in range(rows) for c in range(cols)]
        img = Image.new('I', (cols, rows))
        img.putdata(pil_data)
        img = img.resize((terrain_size, terrain_size), Image.BILINEAR)
        return [min(65535, max(0, int(v))) for v in img.get_flattened_data()]
    except ImportError:
        pass
    rows, cols = dem['rows'], dem['cols']
    grid = dem['grid']
    result = []
    for r in range(terrain_size):
        for c in range(terrain_size):
            gr = r / max(terrain_size - 1, 1) * (rows - 1)
            gc = c / max(terrain_size - 1, 1) * (cols - 1)
            gr0, gc0 = int(gr), int(gc)
            gr1, gc1 = min(gr0+1, rows-1), min(gc0+1, cols-1)
            dr, dc = gr-gr0, gc-gc0
            elev = (grid[gr0][gc0]*(1-dr)*(1-dc) + grid[gr0][gc1]*(1-dr)*dc +
                    grid[gr1][gc0]*dr*(1-dc) + grid[gr1][gc1]*dr*dc)
            result.append(min(65535, max(0, int((elev - base_elev) / MAX_HEIGHT * 65535))))
    return result


# ── Layermap ─────────────────────────────────────────────────────────────────

def build_layermap(feature_polygons, roads, level_size, terrain_size):
    """
    Paint order (lowest to highest):
      1. Base fill: Grass (0)
      2. Feature polygons: parking → Asphalt (2), waterway banks → Dirt (1)
      3. Road stripes: Asphalt (2) on top of everything
    PIL ImageDraw used; row 0 = north in PIL (top), row 0 = south in terrain (bottom).
    """
    half = level_size / 2.0
    n = terrain_size

    def to_px(x, y):
        col = (x + half) / level_size * n
        row = n - (y + half) / level_size * n   # flip: PIL row 0 = top = north
        return int(col), int(row)

    try:
        from PIL import Image, ImageDraw
        img = Image.new('L', (n, n), 0)
        draw = ImageDraw.Draw(img)

        # 1. Feature polygons
        for poly in feature_polygons:
            pts_px = [to_px(p[0], p[1]) for p in poly.get('pts', [])]
            if len(pts_px) >= 3:
                draw.polygon(pts_px, fill=poly.get('layer', 0))

        # 2. Road stripes (drawn last so they override polygon fills)
        for road in roads:
            nodes = road.get('nodes', [])
            if len(nodes) < 2:
                continue
            w_m = float(nodes[0][3]) if len(nodes[0]) >= 4 else 5.0
            w_px = max(1, int(w_m * n / level_size))
            pts = [to_px(nd[0], nd[1]) for nd in nodes]
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i+1]], fill=2, width=w_px)

        return list(img.get_flattened_data())
    except ImportError:
        pass

    # Pure-Python fallback (no polygon fill; only road stripes)
    layer = [0] * (n * n)
    for road in roads:
        nodes = road.get('nodes', [])
        for i in range(len(nodes) - 1):
            c1, r1 = to_px(nodes[i][0], nodes[i][1])
            c2, r2 = to_px(nodes[i+1][0], nodes[i+1][1])
            steps = max(abs(c2-c1), abs(r2-r1), 1)
            for s in range(steps + 1):
                t = s / steps
                c = int(c1 + t*(c2-c1))
                r = int(r1 + t*(r2-r1))
                if 0 <= c < n and 0 <= r < n:
                    layer[r * n + c] = 2
    return layer


# ── .ter binary ──────────────────────────────────────────────────────────────

def make_ter_binary(path, terrain_size, heightmap, layermap):
    n = terrain_size
    materials = ['Grass', 'Dirt', 'Asphalt']
    mat_bytes = struct.pack('<I', len(materials))
    for m in materials:
        enc = m.encode('utf-8')
        mat_bytes += struct.pack('B', len(enc)) + enc
    with open(path, 'wb') as f:
        f.write(struct.pack('B', 9))
        f.write(struct.pack('<I', n))
        f.write(struct.pack(f'<{n*n}H', *heightmap))
        f.write(struct.pack(f'<{n*n}B', *layermap))
        f.write(mat_bytes)


# ── Spawn points ─────────────────────────────────────────────────────────────

SPAWN_STREETS = {
    'spawn_bridge_street':    'Bridge Street',
    'spawn_ballymoney_road':  'Ballymoney Road',
    'spawn_broughshane_road': 'Broughshane Road',
    'spawn_galgorm_road':     'Galgorm Road',
}


def find_spawn_positions(roads, dem, base_elev):
    """Return {spawn_name: (x, y, z)} for named spawn streets."""
    street_to_spawn = {v: k for k, v in SPAWN_STREETS.items()}
    found = {}
    for road in roads:
        name = road.get('name', '')
        if name not in street_to_spawn:
            continue
        sp_name = street_to_spawn[name]
        if sp_name in found:
            continue
        nodes = road.get('nodes', [])
        if not nodes:
            continue
        n = nodes[len(nodes) // 2]
        x, y = n[0], n[1]
        z = (max(0.0, sample_dem(dem, x, y) - base_elev) if dem else 0.0)
        found[sp_name] = (x, y, z)
    return found


def make_player_drop_points(cx, cy, spawn_z, extra_spawns):
    """Default spawn at content centroid + named road spawns."""
    drops = [{
        'name': 'spawn_default',
        'class': 'SpawnSphere',
        'persistentId': new_pid(),
        '__parent': 'PlayerDropPoints',
        'position': [round(cx, 2), round(cy, 2), round(spawn_z + 2.0, 2)],
        'dataBlock': 'SpawnSphereMarker',
        'enabled': '1',
        'homingCount': '0', 'indoorWeight': '1',
        'isAIControlled': '0', 'lockCount': '0',
        'outdoorWeight': '1', 'radius': 6, 'sphereWeight': '1',
    }]
    for sp_name, (x, y, z) in sorted(extra_spawns.items()):
        drops.append({
            'name': sp_name,
            'class': 'SpawnSphere',
            'persistentId': new_pid(),
            '__parent': 'PlayerDropPoints',
            'position': [round(x, 2), round(y, 2), round(z + 2.0, 2)],
            'dataBlock': 'SpawnSphereMarker',
            'enabled': '1',
            'homingCount': '0', 'indoorWeight': '1',
            'isAIControlled': '0', 'lockCount': '0',
            'outdoorWeight': '1', 'radius': 6, 'sphereWeight': '1',
        })
    return drops


# ── Camera bookmarks ─────────────────────────────────────────────────────────

LANDMARK_BUILDINGS = [
    'IMC Ballymena', 'Fairhill Shopping Centre', 'Tower Centre',
    'Seven Towers Leisure Centre', 'Ballymena Bus Station',
]


def find_landmark_bookmarks(buildings, dem, base_elev, level_size):
    """Return list of CameraBookmark objects for named buildings."""
    dist = max(80.0, min(level_size * 0.08, 300.0))
    bookmarks = []
    seen = set()
    for b in buildings:
        name = b.get('name', '')
        if name not in LANDMARK_BUILDINGS or name in seen:
            continue
        seen.add(name)
        x, y = b['position'][0], b['position'][1]
        z = (max(0.0, sample_dem(dem, x, y) - base_elev) if dem else 0.0)
        cam_z = z + dist * 0.6
        slug = name.lower().replace(' ', '_').replace("'", '')
        bookmarks.append({
            'name': f'bookmark_{slug}',
            'internalName': slug,
            'class': 'CameraBookmark',
            'persistentId': new_pid(),
            '__parent': 'CameraBookmarks',
            'position': [round(x, 2), round(y - dist, 2), round(cam_z, 2)],
            'dataBlock': 'CameraBookmarkMarker',
            'isAIControlled': '0',
            'rotationMatrix': [1, 0, 0, 0, 0.7, -0.7, 0, 0.7, 0.7],
        })
    return bookmarks


# ── Level JSON builders ──────────────────────────────────────────────────────

def make_terrain_json(level_size, terrain_size):
    return {
        'binaryFormat': 'version(char), size(unsigned int), heightMap(heightMapSize * heightMapItemSize), layerMap(layerMapSize * layerMapItemSize), materialNames',
        'datafile': '/levels/ballymena/' + TERRAIN_FILENAME,
        'heightMapItemSize': 2, 'heightMapSize': terrain_size * terrain_size,
        'layerMapItemSize': 1, 'layerMapSize': terrain_size * terrain_size,
        'materials': ['Grass', 'Dirt', 'Asphalt'],
        'size': level_size, 'version': 9,
    }


def make_info_json(level_size, spawn_names, preview_filename=None):
    info = {
        'title': 'Ballymena Town Centre',
        'description': (
            'Drive the streets of Ballymena, Co Antrim, Northern Ireland. '
            'OSM road network, SRTM terrain, footways, parking and AI traffic waypoints. '
            f'v{VERSION}'
        ),
        'size': [level_size, level_size],
        'biome': 'Northern Ireland Town',
        'roads': 'OSM: A26 primary, secondary, residential, service, footways',
        'suitablefor': 'Free Roam, Point-to-Point',
        'features': 'SRTM terrain, asphalt/park layermap, AI waypoint graph, footways',
        'authors': 'ballymena-ng-drive (data: © OpenStreetMap, SRTM)',
        'version': VERSION,
        'defaultSpawnPointName': 'spawn_default',
        'spawnPoints': [{'objectname': s} for s in spawn_names],
        'supportsTraffic': True,
        'supportsTimeOfDay': True,
    }
    if preview_filename:
        info['previews'] = [preview_filename]
    return info


def make_sky_and_sun(level_size):
    vis = max(4500, int(level_size * 1.2))
    return [
        {'name': 'tod', 'class': 'TimeOfDay',
         'persistentId': new_pid(), '__parent': 'sky_and_sun',
         'position': [0, 0, 100], 'animate': '0', 'axisTilt': -20,
         'azimuthOverride': 0, 'play': False,
         'rotationMatrix': [1, 0, 0, 0, 1, 0, 0, 0, 1],
         'startTime': 0.58, 'time': 0.58},
        {'name': 'theLevelInfo', 'class': 'LevelInfo',
         'persistentId': new_pid(), '__parent': 'sky_and_sun',
         'canvasClearColor': [1, 1, 1, 255], 'enabled': '1',
         'fogAtmosphereHeight': min(2500, max(800, level_size)),
         'fogColor': [0.72, 0.80, 0.90, 1],
         'fogDensity': max(0.00005, min(0.001, 100.0 / max(level_size, 1))),
         'globalEnviromentMap': 'BNG_Sky_02_cubemap',
         'gravity': -9.81, 'visibleDistance': vis},
        {'name': 'sunsky', 'class': 'ScatterSky',
         'persistentId': new_pid(), '__parent': 'sky_and_sun',
         'position': [0, 0, 100],
         'ambientScale': [0.95, 0.90, 0.86, 1],
         'azimuth': 220, 'elevation': 28,
         'colorize': [0.20, 0.32, 0.58, 1],
         'exposure': 14, 'flareScale': 4,
         'flareType': 'BNG_SunFlare_3',
         'fogScale': [0.38, 0.65, 1, 1],
         'mieScattering': 0.0005,
         'skyBrightness': 38,
         'shadowDistance': min(3200, max(1200, level_size // 2)),
         'shadowSoftness': 0.25},
        {'name': 'clouds', 'class': 'CloudLayer',
         'persistentId': new_pid(), '__parent': 'sky_and_sun',
         'position': [0, 0, 0],
         'coverage': 0.55, 'exposure': 1.3, 'height': 7,
         'windSpeed': 0.04,
         'baseColor': [0.92, 0.93, 0.97, 1]},
    ]


def make_root_main():
    return [{'name': 'MissionGroup', 'class': 'SimGroup',
             'persistentId': new_pid(), 'enabled': '1'}]


def make_mission_group(level_size):
    half = level_size // 2
    objs = [
        {'name': 'theTerrain', 'class': 'TerrainBlock',
         'persistentId': new_pid(), '__parent': 'MissionGroup',
         'position': [-half, -half, 0],
         'maxHeight': MAX_HEIGHT,
         'terrainFile': '/levels/ballymena/' + TERRAIN_FILENAME},
    ]
    groups = [
        ('sky_and_sun',      None),
        ('Buildings',        '1'),
        ('DecalRoads',       None),
        ('Footways',         None),
        ('Waypoints',        '1'),
        ('PhotoSpots',       '1'),
        ('CameraBookmarks',  None),
        ('PlayerDropPoints', '1'),
    ]
    for name, enabled in groups:
        obj = {'name': name, 'class': 'SimGroup',
               'persistentId': new_pid(), '__parent': 'MissionGroup'}
        if enabled:
            obj['enabled'] = enabled
        objs.append(obj)
    return objs


def make_overview_bookmark(cx, cy, spawn_z, level_size):
    dist = max(200.0, min(level_size * 0.35, 2200.0))
    cam_z = spawn_z + max(80.0, min(level_size * 0.12, 400.0))
    return {
        'name': 'overviewbookmark',
        'internalName': 'overview',
        'class': 'CameraBookmark',
        'persistentId': new_pid(),
        '__parent': 'CameraBookmarks',
        'position': [cx, cy - dist, cam_z],
        'dataBlock': 'CameraBookmarkMarker',
        'isAIControlled': '0',
        'rotationMatrix': [1, 0, 0, 0, 0.7, -0.7, 0, 0.7, 0.7],
    }


# ── Preview image ────────────────────────────────────────────────────────────

def make_preview(roads, footways, buildings, feature_polygons):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print('  Preview skipped (Pillow not installed)')
        return
    W, H = 256, 144
    img = Image.new('RGB', (W, H), (45, 62, 45))
    d = ImageDraw.Draw(img)

    all_pts = [(n[0], n[1]) for r in roads for n in r.get('nodes', [])]
    if not all_pts:
        img.save(os.path.join(LEVEL_DIR, 'ballymena_preview.png'))
        return

    xs = [p[0] for p in all_pts]; ys = [p[1] for p in all_pts]
    margin = 10
    scale = min((W - 2*margin) / max(max(xs)-min(xs), 1),
                (H - 2*margin) / max(max(ys)-min(ys), 1))
    ox = margin - min(xs)*scale + (W-2*margin - (max(xs)-min(xs))*scale) / 2
    oy = margin - min(ys)*scale + (H-2*margin - (max(ys)-min(ys))*scale) / 2

    def px(x, y):
        return int(ox + x*scale), int(H - (oy + y*scale))

    # Parking polygons (dark grey)
    for poly in feature_polygons:
        if poly.get('layer') == 2:
            pts_px = [px(p[0], p[1]) for p in poly.get('pts', [])]
            if len(pts_px) >= 3:
                d.polygon(pts_px, fill=(65, 65, 65))

    # Buildings
    for b in buildings:
        bx, by = b['position'][0], b['position'][1]
        sc = b.get('scale', [6, 6, 6])
        hw2, hd2 = sc[0]/2*scale, sc[1]/2*scale
        bpx, bpy = px(bx, by)
        d.rectangle([bpx-hw2, bpy-hd2, bpx+hw2, bpy+hd2], fill=(82, 86, 90))

    # Footways (thin light lines)
    for r in footways:
        nodes = r.get('nodes', [])
        for i in range(len(nodes) - 1):
            d.line([px(nodes[i][0], nodes[i][1]), px(nodes[i+1][0], nodes[i+1][1])],
                   fill=(155, 155, 155), width=1)

    # Roads
    mat_color = {
        'AsphaltRoad_variation_01': (185, 158, 90),
        'AsphaltRoad_variation_02': (145, 132, 105),
        'AsphaltRoad_variation_03': (108, 108, 108),
    }
    for r in roads:
        nodes = r.get('nodes', [])
        if len(nodes) < 2:
            continue
        color = mat_color.get(r.get('material', ''), (100, 100, 100))
        w_px = max(1, int(float(nodes[0][3]) * scale * 0.25))
        for i in range(len(nodes) - 1):
            d.line([px(nodes[i][0], nodes[i][1]), px(nodes[i+1][0], nodes[i+1][1])],
                   fill=color, width=w_px)

    d.text((4, 2), 'Ballymena', fill=(225, 225, 225))
    d.text((4, H - 14), f'Co Antrim, NI  v{VERSION}', fill=(175, 175, 175))
    img.save(os.path.join(LEVEL_DIR, 'ballymena_preview.png'))
    print('  Preview saved')


# ── mod_info.json ────────────────────────────────────────────────────────────

def write_mod_info(dest_dir):
    info = {
        'name': 'ballymena-ng-drive',
        'title': 'Ballymena Town Centre',
        'version': VERSION,
        'author': 'ballymena-ng-drive',
        'description': (
            'Ballymena, Co Antrim, NI — OSM road network, SRTM terrain, '
            'footways/pavements, parking layer, AI traffic waypoints. '
            'Based on OpenStreetMap data (© ODbL contributors) '
            'and NASA SRTM elevation data.'
        ),
        'type': 'level',
    }
    path = os.path.join(dest_dir, 'mod_info.json')
    with open(path, 'w') as f:
        json.dump(info, f, indent=2)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    roads       = load_ndjson(os.path.join(OUT_DIR, 'decal_roads.ndjson'))
    footways    = load_ndjson(os.path.join(OUT_DIR, 'footway_roads.ndjson'))
    buildings   = load_ndjson(os.path.join(OUT_DIR, 'buildings.ndjson'))
    features    = load_ndjson(os.path.join(OUT_DIR, 'feature_polygons.ndjson'))
    waypoints   = load_ndjson(os.path.join(OUT_DIR, 'waypoints.ndjson'))
    photo_spots = load_ndjson(os.path.join(OUT_DIR, 'photo_spots.ndjson'))
    dem         = load_dem()

    if dem:
        print(f'DEM: {dem["rows"]}×{dem["cols"]} grid, '
              f'{dem["min_elev"]:.1f}–{dem["max_elev"]:.1f} m AMSL')
        base_elev = dem['min_elev'] - 2.0
    else:
        print('No DEM — flat terrain (run dem step)')
        base_elev = 0.0

    n_photo_spots = sum(1 for o in photo_spots if o.get('class') == 'TSStatic')
    print(f'Content: {len(roads)} roads, {len(footways)} footways, '
          f'{len(buildings)} buildings, {len(features)} feature polygons, '
          f'{len(waypoints)} waypoints, {n_photo_spots} photo spots')

    bounds = bounds_from_ndjson(roads, buildings)
    if bounds:
        min_x, max_x, min_y, max_y = bounds
        level_size = pick_level_size(min_x, max_x, min_y, max_y)
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        print(f'Content bounds x:[{min_x:.0f},{max_x:.0f}] y:[{min_y:.0f},{max_y:.0f}]')
        print(f'Terrain: {level_size} m world size')
    else:
        level_size = MIN_LEVEL_SIZE
        cx, cy = 0.0, 0.0
        print('No content — defaulting to 1024 m terrain')

    terrain_size = pick_terrain_res(level_size)
    spawn_z = max(0.0, sample_dem(dem, cx, cy) - base_elev) if dem else 0.0

    shutil.rmtree(LEVEL_DIR, ignore_errors=True)
    for sub in ('main/MissionGroup/DecalRoads',
                'main/MissionGroup/Footways',
                'main/MissionGroup/Buildings/buildings_group',
                'main/MissionGroup/Waypoints',
                'main/MissionGroup/PhotoSpots',
                'main/MissionGroup/sky_and_sun',
                'main/MissionGroup/CameraBookmarks',
                'main/MissionGroup/PlayerDropPoints',
                'art/shapes/buildings',
                'art/shapes/billboard',
                'art/shapes/terrain',
                'art/terrain',
                'art/textures/photo_spots',
                'data',
                'scripts'):
        os.makedirs(os.path.join(LEVEL_DIR, sub.replace('/', os.sep)), exist_ok=True)

    # ── Terrain ──────────────────────────────────────────────────────────────
    print(f'Generating terrain ({terrain_size}×{terrain_size} on {level_size}×{level_size} m) …')
    heightmap = build_elevation_array(dem, terrain_size, base_elev)
    print('Painting layermap …')
    layermap = build_layermap(features, roads, level_size, terrain_size)
    make_ter_binary(os.path.join(LEVEL_DIR, TERRAIN_FILENAME), terrain_size, heightmap, layermap)

    shapes_dir = os.path.join(LEVEL_DIR, 'art', 'shapes', 'buildings')
    print('Generating building shapes …')
    generate_unit_box_dae(os.path.join(shapes_dir, 'box.dae'))
    n_shapes = generate_all_shapes(shapes_dir)
    print(f'  {n_shapes} typed shape variants + box.dae fallback')
    generate_billboard_dae(os.path.join(LEVEL_DIR, 'art', 'shapes', 'billboard', 'plane.dae'))

    # ── Satellite ground plane ────────────────────────────────────────────────
    sat_geo = load_satellite_geo()
    sat_plane_obj = None
    if sat_geo and os.path.exists(SAT_PNG_SRC):
        u_max = sat_geo.get('crop_width',  sat_geo.get('tex_width',  1)) / sat_geo['tex_width']
        v_max = sat_geo.get('crop_height', sat_geo.get('tex_height', 1)) / sat_geo['tex_height']
        terrain_dir = os.path.join(LEVEL_DIR, 'art', 'terrain')
        shutil.copy2(SAT_PNG_SRC, os.path.join(terrain_dir, 'satellite.png'))
        sat_dae_path = os.path.join(LEVEL_DIR, 'art', 'shapes', 'terrain', 'satellite_plane.dae')
        generate_sat_plane_dae(sat_dae_path, u_max=u_max, v_max=v_max)
        sat_plane_obj = make_satellite_ground_plane(level_size, u_max, v_max, base_elev)
        print(f'  Satellite ground plane: {os.path.getsize(SAT_PNG_SRC)//1024} KB  '
              f'UV u_max={u_max:.3f} v_max={v_max:.3f}')
    else:
        print('  Satellite ground plane: skipped (run "python run.py satellite" to fetch)')

    # ── Lift Z to terrain height ──────────────────────────────────────────────
    if dem:
        for road in roads:
            for node in road.get('nodes', []):
                while len(node) < 4:
                    node.append(0.0)
                node[2] = round(max(0.0, sample_dem(dem, node[0], node[1]) - base_elev), 2)
        for road in footways:
            for node in road.get('nodes', []):
                while len(node) < 4:
                    node.append(0.0)
                node[2] = round(max(0.0, sample_dem(dem, node[0], node[1]) - base_elev), 2)
        for b in buildings:
            pos = b['position']
            z_ground = max(0.0, sample_dem(dem, pos[0], pos[1]) - base_elev)
            pos[2] = round(z_ground + b['scale'][2] / 2.0, 2)

    # ── Spawn points ──────────────────────────────────────────────────────────
    extra_spawns = find_spawn_positions(roads, dem, base_elev)
    all_spawn_names = ['spawn_default'] + sorted(extra_spawns.keys())
    spawn_objs = make_player_drop_points(cx, cy, spawn_z, extra_spawns)
    print(f'  Spawn points: {len(spawn_objs)} ({", ".join(sp["name"] for sp in spawn_objs)})')

    # ── Camera bookmarks ──────────────────────────────────────────────────────
    landmark_bmarks = find_landmark_bookmarks(buildings, dem, base_elev, level_size)
    overview = make_overview_bookmark(cx, cy, spawn_z, level_size)
    all_bookmarks = [overview] + landmark_bmarks
    print(f'  Camera bookmarks: {len(all_bookmarks)} '
          f'({", ".join(b["name"] for b in all_bookmarks)})')

    # ── Write level files ─────────────────────────────────────────────────────
    print('Writing level files …')
    with open(os.path.join(LEVEL_DIR, 'ballymena.terrain.json'), 'w') as f:
        json.dump(make_terrain_json(level_size, terrain_size), f, indent=2)

    write_items_level(os.path.join(LEVEL_DIR, 'main', 'items.level.json'), make_root_main())
    mission_objs = make_mission_group(level_size)
    if sat_plane_obj:
        mission_objs.append(sat_plane_obj)
    write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'items.level.json'),
                      mission_objs)
    write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'sky_and_sun', 'items.level.json'),
                      make_sky_and_sun(level_size))
    write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'CameraBookmarks', 'items.level.json'),
                      all_bookmarks)
    write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'PlayerDropPoints', 'items.level.json'),
                      spawn_objs)

    if roads:
        write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'DecalRoads', 'items.level.json'),
                          roads)
        print(f'  Roads: {len(roads)}')
    else:
        print('  Warning: no road data')

    if footways:
        write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'Footways', 'items.level.json'),
                          footways)
        print(f'  Footways: {len(footways)}')
    else:
        print('  Warning: no footway data (run process step)')

    if buildings:
        write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'Buildings', 'items.level.json'),
                          [{'name': 'buildings_group', 'class': 'SimGroup',
                            'persistentId': new_pid(), '__parent': 'Buildings'}])
        write_items_level(
            os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'Buildings', 'buildings_group', 'items.level.json'),
            buildings)
        print(f'  Buildings: {len(buildings)}')
    else:
        print('  Warning: no building data')

    if waypoints:
        write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'Waypoints', 'items.level.json'),
                          waypoints)
        print(f'  Waypoints: {len(waypoints)}')
    else:
        write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'Waypoints', 'items.level.json'), [])
        print('  Warning: no waypoint data (run process step)')

    # ── Photo spots ───────────────────────────────────────────────────────────
    write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'PhotoSpots', 'items.level.json'),
                      photo_spots)
    print(f'  Photo spots: {n_photo_spots} billboards '
          f'(run "python run.py photos" to regenerate)')

    # Copy photo composite textures generated by gen_photo_spots.py
    src_tex_dir = os.path.join(OUT_DIR, 'levels', 'ballymena', 'art', 'textures', 'photo_spots')
    dst_tex_dir = os.path.join(LEVEL_DIR, 'art', 'textures', 'photo_spots')
    if os.path.isdir(src_tex_dir) and src_tex_dir != dst_tex_dir:
        for fname in os.listdir(src_tex_dir):
            if fname.endswith('.png'):
                shutil.copy2(os.path.join(src_tex_dir, fname),
                             os.path.join(dst_tex_dir, fname))

    # Bundle manifest + Lua script into the level (for in-game Lua access)
    if os.path.exists(PHOTO_MANIFEST_SRC):
        shutil.copy2(PHOTO_MANIFEST_SRC,
                     os.path.join(LEVEL_DIR, 'data', 'photo_manifest.json'))
    if os.path.exists(LUA_SCRIPT_SRC):
        shutil.copy2(LUA_SCRIPT_SRC,
                     os.path.join(LEVEL_DIR, 'scripts', 'photo_spots.lua'))

    make_preview(roads, footways, buildings, features)

    preview_name = 'ballymena_preview.png'
    preview_arg = preview_name if os.path.isfile(os.path.join(LEVEL_DIR, preview_name)) else None
    with open(os.path.join(LEVEL_DIR, 'info.json'), 'w') as f:
        json.dump(make_info_json(level_size, all_spawn_names, preview_arg), f, indent=2)
    with open(os.path.join(LEVEL_DIR, 'main.decals.json'), 'w') as f:
        json.dump({'header': {'name': 'DecalData File', 'version': 2}, 'instances': {}}, f, indent=2)
    with open(os.path.join(LEVEL_DIR, 'map.json'), 'w') as f:
        json.dump({'segments': {}}, f, indent=2)

    # Legacy cleanup
    for legacy in ('items.items.json', 'main.mission', 'scenes'):
        p = os.path.join(LEVEL_DIR, legacy)
        if os.path.isfile(p):
            os.remove(p)
        elif os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    # Also clean output root artefact from old builds
    old_items = os.path.join(OUT_DIR, 'items.items.json')
    if os.path.isfile(old_items):
        os.remove(old_items)
        print('  Removed legacy output/items.items.json')

    print(f'\nLevel built → {LEVEL_DIR}  (v{VERSION})')
    print(f'Spawn ({cx:.0f}, {cy:.0f}, {spawn_z+2:.1f}) | '
          f'terrain {level_size} m | {terrain_size}² samples')


if __name__ == '__main__':
    main()
