#!/usr/bin/env python3
"""Build the Ballymena BeamNG level.

Improvements over v1:
• BBOX-clipped content → level_size typically 4096 m (was 8192).
• Terrain heightmap from SRTM DEM grid (data/dem/elevation_grid.json) via PIL resize.
• Terrain layermap painted with asphalt under every road using PIL/ImageDraw.
• Road node Z and building Z lifted to local terrain height from DEM.
• Sky tuned for an overcast Northern Irish afternoon.
"""
import json, os, struct, uuid, shutil
from gen_box_dae import generate_unit_box_dae
from utils import get_bbox_meters, sample_dem

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, 'output')
LEVEL_DIR = os.path.join(OUT_DIR, 'levels', 'ballymena')
DEM_PATH = os.path.join(BASE_DIR, 'data', 'dem', 'elevation_grid.json')

TERRAIN_FILENAME = 'ballymena.ter'
MAX_HEIGHT = 120          # metres; uint16 → h_m = value / 65535 * MAX_HEIGHT
MIN_LEVEL_SIZE = 1024
MAX_LEVEL_SIZE = 8192
BOUNDS_MARGIN = 1.18


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
        return None
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def load_dem():
    if not os.path.exists(DEM_PATH):
        return None
    with open(DEM_PATH) as f:
        return json.load(f)


# ── Terrain sizing ───────────────────────────────────────────────────────────

def bounds_from_ndjson(roads, buildings):
    xs, ys = [], []
    for r in (roads or []):
        for n in r.get('nodes', []):
            if len(n) >= 2:
                xs.append(float(n[0]))
                ys.append(float(n[1]))
    for b in (buildings or []):
        pos = b.get('position')
        if pos and len(pos) >= 2:
            xs.append(float(pos[0]))
            ys.append(float(pos[1]))
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def pick_level_size(min_x, max_x, min_y, max_y):
    half = max(abs(min_x), abs(max_x), abs(min_y), abs(max_y))
    need = 2.0 * half * BOUNDS_MARGIN
    size = MIN_LEVEL_SIZE
    while size < need and size < MAX_LEVEL_SIZE:
        size *= 2
    return min(max(size, MIN_LEVEL_SIZE), MAX_LEVEL_SIZE)


def pick_terrain_res(level_size):
    return min(4096, max(1024, min(level_size, 4096)))


# ── Elevation helpers ────────────────────────────────────────────────────────

def build_elevation_array(dem, terrain_size, base_elev):
    """
    Return flat list of uint16 values (row-major, row 0 = south end of terrain).
    Uses PIL.Image.resize for fast bilinear upscale from the DEM grid.
    Falls back to all-zeros if DEM is unavailable or PIL missing.
    """
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
        return list(img.get_flattened_data())
    except ImportError:
        pass
    # Pure-Python fallback (slow on large grids)
    rows, cols = dem['rows'], dem['cols']
    grid = dem['grid']
    result = []
    for r in range(terrain_size):
        for c in range(terrain_size):
            gr = r / (terrain_size - 1) * (rows - 1) if terrain_size > 1 else 0
            gc = c / (terrain_size - 1) * (cols - 1) if terrain_size > 1 else 0
            gr0, gc0 = int(gr), int(gc)
            gr1 = min(gr0 + 1, rows - 1)
            gc1 = min(gc0 + 1, cols - 1)
            dr, dc = gr - gr0, gc - gc0
            elev = (grid[gr0][gc0] * (1-dr)*(1-dc) + grid[gr0][gc1] * (1-dr)*dc +
                    grid[gr1][gc0] * dr*(1-dc) + grid[gr1][gc1] * dr*dc)
            h = max(0.0, elev - base_elev)
            result.append(min(65535, int(h / MAX_HEIGHT * 65535)))
    return result


def build_layermap(roads, level_size, terrain_size):
    """
    Flat list of uint8 layer indices: 0=Grass, 1=Dirt, 2=Asphalt.
    Rasterises each DecalRoad as an asphalt stripe using PIL/ImageDraw;
    falls back to pure-Python Bresenham if PIL is unavailable.
    """
    half = level_size / 2.0
    n = terrain_size

    def to_px(x, y):
        col = (x + half) / level_size * n
        # PIL row 0 = top (north), terrain row 0 = south — flip
        row = n - (y + half) / level_size * n
        return int(col), int(row)

    try:
        from PIL import Image, ImageDraw
        img = Image.new('L', (n, n), 0)
        draw = ImageDraw.Draw(img)
        for road in (roads or []):
            nodes = road.get('nodes', [])
            if len(nodes) < 2:
                continue
            # Width is stored in node[3]; use first node's value
            w_m = float(nodes[0][3]) if len(nodes[0]) >= 4 else 5.0
            w_px = max(1, int(w_m * n / level_size))
            pts = [to_px(nd[0], nd[1]) for nd in nodes]
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i+1]], fill=2, width=w_px)
        return list(img.get_flattened_data())
    except ImportError:
        pass

    # Bresenham fallback (no width)
    layer = [0] * (n * n)
    for road in (roads or []):
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
    hm = struct.pack(f'<{n*n}H', *heightmap)
    lm = struct.pack(f'<{n*n}B', *layermap)
    mat_bytes = struct.pack('<I', len(materials))
    for m in materials:
        enc = m.encode('utf-8')
        mat_bytes += struct.pack('B', len(enc)) + enc
    with open(path, 'wb') as f:
        f.write(struct.pack('B', 9))
        f.write(struct.pack('<I', n))
        f.write(hm)
        f.write(lm)
        f.write(mat_bytes)


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


def make_info_json(level_size, preview_filename=None):
    info = {
        'title': 'Ballymena Town Centre',
        'description': 'Drive the streets of Ballymena, Co Antrim, Northern Ireland — OSM road network with real SRTM terrain elevation.',
        'size': [level_size, level_size],
        'biome': 'Northern Ireland Town',
        'roads': 'OSM road network — primary, secondary, residential, service roads',
        'suitablefor': 'Free Roam',
        'features': 'OSM roads + buildings, SRTM terrain heightmap, asphalt layermap',
        'authors': 'ballymena-ng-drive (OSM contributors / SRTM)',
        'defaultSpawnPointName': 'spawn_default',
        'spawnPoints': [{'objectname': 'spawn_default'}],
        'supportsTraffic': False,
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
    for name, enabled in [('sky_and_sun', None), ('Buildings', '1'),
                          ('DecalRoads', None), ('CameraBookmarks', None),
                          ('PlayerDropPoints', '1')]:
        obj = {'name': name, 'class': 'SimGroup',
               'persistentId': new_pid(), '__parent': 'MissionGroup'}
        if enabled:
            obj['enabled'] = enabled
        objs.append(obj)
    return objs


def make_camera_bookmarks(cx, cy, spawn_z, level_size):
    dist = max(180.0, min(level_size * 0.35, 2200.0))
    cam_z = spawn_z + max(60.0, min(level_size * 0.12, 350.0))
    return [{
        'name': 'overviewbookmark',
        'internalName': 'overview',
        'class': 'CameraBookmark',
        'persistentId': new_pid(),
        '__parent': 'CameraBookmarks',
        'position': [cx, cy - dist, cam_z],
        'dataBlock': 'CameraBookmarkMarker',
        'isAIControlled': '0',
        'rotationMatrix': [1, 0, 0, 0, 0.7, -0.7, 0, 0.7, 0.7],
    }]


def make_player_drop_points(cx, cy, spawn_z):
    return [{
        'name': 'spawn_default',
        'class': 'SpawnSphere',
        'persistentId': new_pid(),
        '__parent': 'PlayerDropPoints',
        'position': [round(cx, 2), round(cy, 2), round(spawn_z + 2.0, 2)],
        'dataBlock': 'SpawnSphereMarker',
        'enabled': '1',
        'homingCount': '0', 'indoorWeight': '1',
        'isAIControlled': '0', 'lockCount': '0',
        'outdoorWeight': '1', 'radius': 5, 'sphereWeight': '1',
    }]


# ── Preview image ────────────────────────────────────────────────────────────

def make_preview(roads, buildings):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print('  Preview skipped (Pillow not installed)')
        return
    W, H = 256, 144
    img = Image.new('RGB', (W, H), (45, 62, 45))
    d = ImageDraw.Draw(img)

    all_pts = [(n[0], n[1]) for r in (roads or []) for n in r.get('nodes', [])]
    if not all_pts:
        img.save(os.path.join(LEVEL_DIR, 'ballymena_preview.png'))
        return

    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    margin = 12
    rng_x = max(max(xs) - min(xs), 1.0)
    rng_y = max(max(ys) - min(ys), 1.0)
    scale = min((W - 2*margin) / rng_x, (H - 2*margin) / rng_y)
    ox = margin + (W - 2*margin - rng_x*scale) / 2 - min(xs)*scale
    oy = margin + (H - 2*margin - rng_y*scale) / 2 - min(ys)*scale

    def px(x, y):
        return int(ox + x*scale), int(H - (oy + y*scale))

    # Buildings as grey boxes
    for b in (buildings or []):
        bx, by = b['position'][0], b['position'][1]
        sc = b.get('scale', [6, 6, 6])
        hw2, hd2 = sc[0]/2*scale, sc[1]/2*scale
        bpx, bpy = px(bx, by)
        d.rectangle([bpx-hw2, bpy-hd2, bpx+hw2, bpy+hd2], fill=(85, 88, 92))

    # Roads — colour by material variant
    mat_color = {
        'AsphaltRoad_variation_01': (180, 155, 95),
        'AsphaltRoad_variation_02': (148, 132, 108),
        'AsphaltRoad_variation_03': (108, 108, 108),
    }
    for r in (roads or []):
        nodes = r.get('nodes', [])
        if len(nodes) < 2:
            continue
        color = mat_color.get(r.get('material', ''), (100, 100, 100))
        w_px = max(1, int(float(nodes[0][3]) * scale * 0.25))
        for i in range(len(nodes) - 1):
            d.line([px(nodes[i][0], nodes[i][1]), px(nodes[i+1][0], nodes[i+1][1])],
                   fill=color, width=w_px)

    d.text((4, 2), 'Ballymena', fill=(220, 220, 220))
    d.text((4, H - 14), 'Co Antrim, NI', fill=(180, 180, 180))
    img.save(os.path.join(LEVEL_DIR, 'ballymena_preview.png'))
    print('  Preview saved')


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    roads = load_ndjson(os.path.join(OUT_DIR, 'decal_roads.ndjson')) or []
    buildings = load_ndjson(os.path.join(OUT_DIR, 'buildings.ndjson')) or []
    dem = load_dem()

    if dem:
        print(f'DEM loaded: {dem["rows"]}×{dem["cols"]} grid, '
              f'{dem["min_elev"]:.1f}–{dem["max_elev"]:.1f} m AMSL')
        base_elev = dem['min_elev'] - 2.0
    else:
        print('No DEM — flat terrain (run fetch_dem.py to add elevation)')
        base_elev = 0.0

    bounds = bounds_from_ndjson(roads, buildings)
    if bounds:
        min_x, max_x, min_y, max_y = bounds
        level_size = pick_level_size(min_x, max_x, min_y, max_y)
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        print(f'Content bounds x:[{min_x:.0f},{max_x:.0f}] y:[{min_y:.0f},{max_y:.0f}]')
        print(f'Terrain world size: {level_size} m')
        half = level_size / 2.0
        for v in (min_x, max_x, min_y, max_y):
            if abs(v) > half:
                print(f'  WARNING: coord {v:.0f} exceeds terrain half-extent {half:.0f}')
    else:
        level_size = MIN_LEVEL_SIZE
        cx, cy = 0.0, 0.0
        print('No content NDJSON — defaulting to 1024 m terrain')

    terrain_size = pick_terrain_res(level_size)
    spawn_z = max(0.0, sample_dem(dem, cx, cy) - base_elev) if dem else 0.0

    shutil.rmtree(LEVEL_DIR, ignore_errors=True)
    for sub in ('main/MissionGroup/DecalRoads',
                'main/MissionGroup/Buildings/buildings_group',
                'main/MissionGroup/sky_and_sun',
                'main/MissionGroup/CameraBookmarks',
                'main/MissionGroup/PlayerDropPoints',
                'art/shapes/buildings'):
        os.makedirs(os.path.join(LEVEL_DIR, sub.replace('/', os.sep)), exist_ok=True)

    print(f'Generating terrain ({terrain_size}×{terrain_size} on {level_size}×{level_size} m) …')
    heightmap = build_elevation_array(dem, terrain_size, base_elev)
    print('Painting layermap …')
    layermap = build_layermap(roads, level_size, terrain_size)
    make_ter_binary(os.path.join(LEVEL_DIR, TERRAIN_FILENAME), terrain_size, heightmap, layermap)

    print('Generating building shape …')
    generate_unit_box_dae(os.path.join(LEVEL_DIR, 'art', 'shapes', 'buildings', 'box.dae'))

    # Lift road node Z to terrain height (DecalRoad projects onto terrain; Z prevents burial)
    if dem and roads:
        for road in roads:
            for node in road.get('nodes', []):
                while len(node) < 4:
                    node.append(0.0)
                node[2] = round(max(0.0, sample_dem(dem, node[0], node[1]) - base_elev), 2)

    # Lift building centre Z to terrain_height + half_building_height
    if dem and buildings:
        for b in buildings:
            pos = b['position']
            z_ground = max(0.0, sample_dem(dem, pos[0], pos[1]) - base_elev)
            pos[2] = round(z_ground + b['scale'][2] / 2.0, 2)

    print('Writing level files …')
    with open(os.path.join(LEVEL_DIR, 'ballymena.terrain.json'), 'w') as f:
        json.dump(make_terrain_json(level_size, terrain_size), f, indent=2)

    write_items_level(os.path.join(LEVEL_DIR, 'main', 'items.level.json'), make_root_main())
    write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'items.level.json'),
                      make_mission_group(level_size))
    write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'sky_and_sun', 'items.level.json'),
                      make_sky_and_sun(level_size))
    write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'CameraBookmarks', 'items.level.json'),
                      make_camera_bookmarks(cx, cy, spawn_z, level_size))
    write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'PlayerDropPoints', 'items.level.json'),
                      make_player_drop_points(cx, cy, spawn_z))

    if roads:
        write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'DecalRoads', 'items.level.json'),
                          roads)
        print(f'  Roads: {len(roads)} DecalRoad objects')
    else:
        print('  Warning: no road data')

    if buildings:
        write_items_level(os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'Buildings', 'items.level.json'),
                          [{'name': 'buildings_group', 'class': 'SimGroup',
                            'persistentId': new_pid(), '__parent': 'Buildings'}])
        write_items_level(
            os.path.join(LEVEL_DIR, 'main', 'MissionGroup', 'Buildings', 'buildings_group', 'items.level.json'),
            buildings)
        print(f'  Buildings: {len(buildings)} TSStatic objects')
    else:
        print('  Warning: no building data')

    make_preview(roads, buildings)
    preview_name = 'ballymena_preview.png'
    preview_arg = preview_name if os.path.isfile(os.path.join(LEVEL_DIR, preview_name)) else None
    with open(os.path.join(LEVEL_DIR, 'info.json'), 'w') as f:
        json.dump(make_info_json(level_size, preview_arg), f, indent=2)
    with open(os.path.join(LEVEL_DIR, 'main.decals.json'), 'w') as f:
        json.dump({'header': {'name': 'DecalData File', 'version': 2}, 'instances': {}}, f, indent=2)
    with open(os.path.join(LEVEL_DIR, 'map.json'), 'w') as f:
        json.dump({'segments': {}}, f, indent=2)

    for legacy in ('items.items.json', 'main.mission', 'scenes'):
        p = os.path.join(LEVEL_DIR, legacy)
        if os.path.isfile(p):
            os.remove(p)
        elif os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)

    print(f'\nLevel built → {LEVEL_DIR}')
    print(f'Spawn ({cx:.0f}, {cy:.0f}, {spawn_z+2:.1f}) | terrain {level_size} m | {terrain_size}² samples')


if __name__ == '__main__':
    main()
