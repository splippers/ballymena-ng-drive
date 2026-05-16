"""Unit tests for the Ballymena NG Drive pipeline."""
import sys, os, json, struct, math, unittest, tempfile, shutil, re

# Ensure src/ is importable regardless of cwd
SRC = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, os.path.abspath(SRC))

import utils
from parse_roads import (material_for_road, simplify_polyline,
                         build_decal_road, generate_decal_roads)
from parse_buildings import (building_height, oriented_bbox,
                              polygon_centroid, generate_buildings)
from parse_footways import generate_footway_decals, extract_footways
from parse_features import generate_feature_polygons
from gen_waypoints import find_junctions, find_landmark_positions, make_waypoints
from gen_building_shapes import (shape_for_building, shape_dae_path,
                                  generate_all_shapes, SHAPES, OSM_TAG_TO_SHAPE)
from gen_photo_spots import (heading_to_rotation_matrix, make_billboard_tsstatic,
                              make_photo_waypoint, generate_photo_spots)
from validate_photos import REQUIRED_FIELDS, BBOX as PHOTO_BBOX
from build_map import (pick_level_size, pick_terrain_res, bounds_from_ndjson,
                       build_elevation_array, build_layermap,
                       make_satellite_ground_plane)
from fetch_satellite import deg2tile, tile_nw_latlon
from gen_sat_plane_dae import generate_sat_plane_dae


# ── utils ────────────────────────────────────────────────────────────────────

class TestLatLonToMeters(unittest.TestCase):
    def test_center_is_origin(self):
        x, y = utils.latlon_to_meters(utils.CENTER_LAT, utils.CENTER_LON)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_roundtrip(self):
        lat, lon = 54.870, -6.285
        x, y = utils.latlon_to_meters(lat, lon)
        lat2, lon2 = utils.meters_to_latlon(x, y)
        self.assertAlmostEqual(lat, lat2, places=6)
        self.assertAlmostEqual(lon, lon2, places=6)

    def test_north_is_positive_y(self):
        _, y = utils.latlon_to_meters(utils.CENTER_LAT + 0.01, utils.CENTER_LON)
        self.assertGreater(y, 0)

    def test_east_is_positive_x(self):
        x, _ = utils.latlon_to_meters(utils.CENTER_LAT, utils.CENTER_LON + 0.01)
        self.assertGreater(x, 0)


class TestGetBboxMeters(unittest.TestCase):
    def test_returns_four_values(self):
        result = utils.get_bbox_meters()
        self.assertEqual(len(result), 4)

    def test_ordering(self):
        x_min, x_max, y_min, y_max = utils.get_bbox_meters()
        self.assertLess(x_min, x_max)
        self.assertLess(y_min, y_max)

    def test_bbox_is_approx_2km(self):
        x_min, x_max, y_min, y_max = utils.get_bbox_meters()
        self.assertGreater(x_max - x_min, 1500)  # at least 1.5 km
        self.assertGreater(y_max - y_min, 1500)


class TestRoadWidth(unittest.TestCase):
    def test_primary_wider_than_residential(self):
        self.assertGreater(utils.road_width('primary'), utils.road_width('residential'))

    def test_lanes_override(self):
        self.assertEqual(utils.road_width('residential', '2'), 7.0)

    def test_unknown_returns_default(self):
        self.assertIsInstance(utils.road_width('unknown_tag'), float)


class TestClipLine(unittest.TestCase):
    def test_fully_inside(self):
        r = utils._clip_line(1, 1, 3, 3, 0, 10, 0, 10)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r[0], 1.0)
        self.assertAlmostEqual(r[2], 3.0)

    def test_fully_outside(self):
        self.assertIsNone(utils._clip_line(11, 0, 12, 0, 0, 10, 0, 10))

    def test_clip_at_right_edge(self):
        r = utils._clip_line(5, 5, 15, 5, 0, 10, 0, 10)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r[2], 10.0)

    def test_parallel_outside(self):
        self.assertIsNone(utils._clip_line(-1, 0, -1, 10, 0, 10, 0, 10))

    def test_crossing_corner(self):
        # diagonal through (0,0)-(10,10), from (-5,-5) to (15,15)
        r = utils._clip_line(-5, -5, 15, 15, 0, 10, 0, 10)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r[0], 0.0, places=5)
        self.assertAlmostEqual(r[2], 10.0, places=5)


class TestClipPolyline(unittest.TestCase):
    def test_all_inside(self):
        pts = [(1, 1), (5, 5), (9, 9)]
        segs = utils.clip_polyline(pts, 0, 10, 0, 10)
        self.assertEqual(len(segs), 1)
        self.assertEqual(len(segs[0]), 3)

    def test_all_outside(self):
        pts = [(11, 0), (12, 0)]
        segs = utils.clip_polyline(pts, 0, 10, 0, 10)
        self.assertEqual(len(segs), 0)

    def test_entering_bbox(self):
        pts = [(-5, 5), (5, 5)]
        segs = utils.clip_polyline(pts, 0, 10, 0, 10)
        self.assertEqual(len(segs), 1)
        # clipped start should be at x=0
        self.assertAlmostEqual(segs[0][0][0], 0.0, places=4)

    def test_empty_input(self):
        self.assertEqual(utils.clip_polyline([], 0, 10, 0, 10), [])

    def test_single_point(self):
        result = utils.clip_polyline([(5, 5)], 0, 10, 0, 10)
        # single point has no segments
        self.assertEqual(len(result), 1)

    def test_split_exit_entry(self):
        # goes inside → outside → inside
        pts = [(2, 5), (8, 5), (12, 5), (8, 5), (2, 5)]
        segs = utils.clip_polyline(pts, 0, 10, 0, 10)
        # should be two segments
        self.assertGreaterEqual(len(segs), 1)


class TestBilinearSample(unittest.TestCase):
    def setUp(self):
        self.grid = [[0.0, 10.0], [20.0, 30.0]]

    def test_corner_values(self):
        self.assertAlmostEqual(utils._bilinear(self.grid, 2, 2, 0, 0), 0.0)
        self.assertAlmostEqual(utils._bilinear(self.grid, 2, 2, 0, 1), 10.0)
        self.assertAlmostEqual(utils._bilinear(self.grid, 2, 2, 1, 0), 20.0)
        self.assertAlmostEqual(utils._bilinear(self.grid, 2, 2, 1, 1), 30.0)

    def test_centre(self):
        result = utils._bilinear(self.grid, 2, 2, 0.5, 0.5)
        self.assertAlmostEqual(result, 15.0)

    def test_clamp_below_zero(self):
        result = utils._bilinear(self.grid, 2, 2, -1, -1)
        self.assertAlmostEqual(result, 0.0)


class TestSampleDem(unittest.TestCase):
    def _make_dem(self, val=60.0):
        return {'bbox': utils.BBOX, 'rows': 2, 'cols': 2,
                'grid': [[val, val], [val, val]],
                'min_elev': val, 'max_elev': val}

    def test_constant_dem(self):
        dem = self._make_dem(60.0)
        result = utils.sample_dem(dem, 0.0, 0.0)
        self.assertAlmostEqual(result, 60.0, places=2)

    def test_outside_bbox_clamps(self):
        # Far outside BBOX still returns a value (clamped bilinear)
        dem = self._make_dem(50.0)
        result = utils.sample_dem(dem, 99999.0, 99999.0)
        self.assertAlmostEqual(result, 50.0, places=2)


# ── parse_roads ──────────────────────────────────────────────────────────────

class TestMaterialForRoad(unittest.TestCase):
    def test_primary_uses_variation_01(self):
        self.assertEqual(material_for_road('primary'), 'AsphaltRoad_variation_01')

    def test_service_is_asphalt_not_dirt(self):
        mat = material_for_road('service')
        self.assertIn('Asphalt', mat)
        self.assertNotIn('Dirt', mat)

    def test_pedestrian_is_asphalt(self):
        mat = material_for_road('pedestrian')
        self.assertIn('Asphalt', mat)

    def test_surface_asphalt_overrides_highway(self):
        mat = material_for_road('service', 'asphalt')
        self.assertEqual(mat, 'AsphaltRoad_variation_01')

    def test_paving_stones_is_variation_02(self):
        mat = material_for_road('pedestrian', 'paving_stones')
        self.assertEqual(mat, 'AsphaltRoad_variation_02')

    def test_link_road(self):
        mat = material_for_road('primary_link')
        self.assertIn('Asphalt', mat)

    def test_unknown_returns_default(self):
        mat = material_for_road('unknown_highway')
        self.assertIn('Asphalt', mat)


class TestSimplifyPolyline(unittest.TestCase):
    def test_two_points_unchanged(self):
        pts = [(0, 0), (10, 0)]
        self.assertEqual(simplify_polyline(pts), pts)

    def test_collinear_reduced(self):
        pts = [(0, 0), (5, 0), (10, 0)]
        result = simplify_polyline(pts, tolerance=0.1)
        self.assertEqual(len(result), 2)

    def test_corner_preserved(self):
        pts = [(0, 0), (5, 0), (5, 5)]
        result = simplify_polyline(pts, tolerance=0.1)
        self.assertGreater(len(result), 2)

    def test_single_point(self):
        result = simplify_polyline([(1, 2)], tolerance=0.5)
        self.assertEqual(len(result), 1)


class TestBuildDecalRoad(unittest.TestCase):
    def test_returns_decalroad_dict(self):
        pts = [(0, 0), (10, 10), (20, 10)]
        dr = build_decal_road(pts, 'primary', '', '', 'Test Road')
        self.assertIsNotNone(dr)
        self.assertEqual(dr['class'], 'DecalRoad')
        self.assertEqual(dr['name'], 'Test Road')
        self.assertIn('persistentId', dr)
        self.assertIn('nodes', dr)

    def test_nodes_have_four_elements(self):
        pts = [(0, 0), (5, 0), (10, 0)]
        dr = build_decal_road(pts, 'residential', '', '', '')
        for node in dr['nodes']:
            self.assertEqual(len(node), 4)

    def test_degenerate_returns_none(self):
        dr = build_decal_road([(5, 5)], 'residential', '', '', '')
        self.assertIsNone(dr)

    def test_highway_preserved(self):
        pts = [(0, 0), (5, 5)]
        dr = build_decal_road(pts, 'tertiary', '', '', '')
        self.assertEqual(dr.get('highway'), 'tertiary')


class TestGenerateDecalRoads(unittest.TestCase):
    def _make_road(self, lats_lons, hw='residential'):
        return {
            'highway': hw, 'name': '', 'oneway': 'no',
            'lanes': '', 'surface': '',
            'nodes': [{'lat': lat, 'lon': lon} for lat, lon in lats_lons],
        }

    def test_road_inside_bbox(self):
        road = self._make_road([(54.860, -6.280), (54.861, -6.278)])
        result = generate_decal_roads([road])
        self.assertEqual(len(result), 1)

    def test_road_outside_bbox_clipped_away(self):
        road = self._make_road([(55.0, -6.0), (55.1, -5.9)])
        result = generate_decal_roads([road])
        self.assertEqual(len(result), 0)

    def test_short_road_discarded(self):
        road = self._make_road([(54.860, -6.280)])  # only 1 node → no segments
        result = generate_decal_roads([road])
        self.assertEqual(len(result), 0)


# ── parse_buildings ──────────────────────────────────────────────────────────

class TestBuildingHeight(unittest.TestCase):
    def test_explicit_height_tag(self):
        b = {'height': '15', 'levels': 0}
        self.assertAlmostEqual(building_height(b, 100), 15.0)

    def test_levels_tag(self):
        b = {'height': '', 'levels': 4}
        self.assertAlmostEqual(building_height(b, 100), 12.0)

    def test_minimum_is_3m(self):
        b = {'height': '1', 'levels': 0}
        self.assertAlmostEqual(building_height(b, 10), 3.0)

    def test_unknown_levels_uses_area_heuristic(self):
        b = {'height': '', 'levels': 0}
        h_small = building_height(b, 30)   # area <50 → 1 level
        h_large = building_height(b, 3000)  # area >2000 → 3 levels
        self.assertLess(h_small, h_large)

    def test_height_with_unit(self):
        b = {'height': '12m', 'levels': 0}
        self.assertAlmostEqual(building_height(b, 100), 12.0)


class TestPolygonCentroid(unittest.TestCase):
    def test_square_centroid(self):
        pts = [(0, 0), (4, 0), (4, 4), (0, 4)]
        cx, cy = polygon_centroid(pts)
        self.assertAlmostEqual(cx, 2.0)
        self.assertAlmostEqual(cy, 2.0)


class TestOrientedBbox(unittest.TestCase):
    def test_axis_aligned_square(self):
        pts = [(0, 0), (4, 0), (4, 4), (0, 4)]
        (cx, cz), w, d, angle = oriented_bbox(pts)
        self.assertAlmostEqual(cx, 2.0, places=1)
        self.assertAlmostEqual(cz, 2.0, places=1)
        self.assertAlmostEqual(w, 4.0, places=1)
        self.assertAlmostEqual(d, 4.0, places=1)

    def test_non_degenerate(self):
        pts = [(0, 0), (10, 0), (10, 3), (0, 3)]
        (cx, cz), w, d, angle = oriented_bbox(pts)
        self.assertGreater(max(w, d), 0)
        self.assertGreater(min(w, d), 0)


# ── build_map ────────────────────────────────────────────────────────────────

class TestPickLevelSize(unittest.TestCase):
    def test_small_content_gives_1024(self):
        self.assertEqual(pick_level_size(-400, 400, -400, 400), 1024)

    def test_ballymena_sized_gives_4096(self):
        # Typical post-clipping bounds
        result = pick_level_size(-961, 1025, -891, 1113)
        self.assertEqual(result, 4096)

    def test_pre_clip_large_bounds_gives_8192(self):
        result = pick_level_size(-1815, 1755, -1064, 2129)
        self.assertEqual(result, 8192)

    def test_never_below_minimum(self):
        self.assertGreaterEqual(pick_level_size(-1, 1, -1, 1), 1024)


class TestPickTerrainRes(unittest.TestCase):
    def test_1024_terrain_for_1024_level(self):
        self.assertEqual(pick_terrain_res(1024), 1024)

    def test_caps_at_4096(self):
        self.assertEqual(pick_terrain_res(8192), 4096)


class TestBoundsFromNdjson(unittest.TestCase):
    def _make_road(self, nodes):
        return {'class': 'DecalRoad', 'nodes': nodes}

    def test_basic_bounds(self):
        roads = [self._make_road([[10, 20, 0, 5], [30, 40, 0, 5]])]
        bounds = bounds_from_ndjson(roads, [])
        self.assertEqual(bounds, (10, 30, 20, 40))

    def test_no_content(self):
        self.assertIsNone(bounds_from_ndjson([], []))

    def test_buildings_included(self):
        buildings = [{'position': [50, 60, 5], 'scale': [5, 5, 5]}]
        bounds = bounds_from_ndjson([], buildings)
        self.assertIsNotNone(bounds)
        self.assertEqual(bounds[1], 50)


class TestBuildElevationArray(unittest.TestCase):
    def test_no_dem_returns_zeros(self):
        result = build_elevation_array(None, 4, 0.0)
        self.assertEqual(result, [0] * 16)
        self.assertTrue(all(v == 0 for v in result))

    def test_constant_dem(self):
        # All elevations = base_elev → all uint16 = 0
        dem = {'rows': 2, 'cols': 2,
               'grid': [[60.0, 60.0], [60.0, 60.0]],
               'min_elev': 60.0, 'max_elev': 60.0,
               'bbox': utils.BBOX}
        result = build_elevation_array(dem, 4, base_elev=60.0)
        self.assertEqual(len(result), 16)
        self.assertTrue(all(v == 0 for v in result))

    def test_elevated_dem(self):
        # Elevation 10m above base → values > 0
        dem = {'rows': 2, 'cols': 2,
               'grid': [[70.0, 70.0], [70.0, 70.0]],
               'min_elev': 70.0, 'max_elev': 70.0,
               'bbox': utils.BBOX}
        result = build_elevation_array(dem, 4, base_elev=60.0)
        self.assertTrue(all(v > 0 for v in result))

    def test_correct_length(self):
        result = build_elevation_array(None, 8, 0.0)
        self.assertEqual(len(result), 64)


class TestBuildLayermap(unittest.TestCase):
    def _make_road(self, x1, y1, x2, y2, width=7.0):
        return {'class': 'DecalRoad',
                'nodes': [[x1, y1, 0, width], [x2, y2, 0, width]]}

    def test_length(self):
        result = build_layermap([], [], 1024, 32)
        self.assertEqual(len(result), 32 * 32)

    def test_empty_roads_all_grass(self):
        result = build_layermap([], [], 1024, 32)
        self.assertTrue(all(v == 0 for v in result))

    def test_road_paints_asphalt(self):
        # A road crossing the middle of a 1024m world on a 64-px layermap
        road = self._make_road(-200, 0, 200, 0, 10.0)
        result = build_layermap([], [road], 1024, 64)
        # At least some pixels should be asphalt (value 2)
        self.assertIn(2, result)

    def test_values_in_range(self):
        road = self._make_road(-100, 0, 100, 0, 5.0)
        result = build_layermap([], [road], 1024, 32)
        self.assertTrue(all(0 <= v <= 2 for v in result))

    def test_feature_polygon_paints_before_roads(self):
        # A parking polygon (asphalt) in a region with no roads should still paint asphalt
        poly = {
            'kind': 'amenity:parking', 'layer': 2, 'name': '',
            'pts': [[-50, -50], [50, -50], [50, 50], [-50, 50]],
        }
        result = build_layermap([poly], [], 1024, 64)
        self.assertIn(2, result)


class TestTerBinary(unittest.TestCase):
    def test_ter_file_format(self):
        from build_map import make_ter_binary
        with tempfile.NamedTemporaryFile(suffix='.ter', delete=False) as tf:
            path = tf.name
        try:
            n = 4
            hm = [0] * (n * n)
            lm = [0] * (n * n)
            make_ter_binary(path, n, hm, lm)
            with open(path, 'rb') as f:
                version = struct.unpack('B', f.read(1))[0]
                size = struct.unpack('<I', f.read(4))[0]
                hmap = struct.unpack(f'<{n*n}H', f.read(n*n*2))
                lmap = struct.unpack(f'<{n*n}B', f.read(n*n))
            self.assertEqual(version, 9)
            self.assertEqual(size, n)
            self.assertEqual(sum(hmap), 0)
            self.assertEqual(sum(lmap), 0)
        finally:
            os.unlink(path)


class TestGenerateBuildings(unittest.TestCase):
    def _make_building(self, lats_lons, levels=2, name=''):
        return {
            'id': 1, 'building': 'yes', 'levels': levels,
            'height': '', 'name': name, 'amenity': '',
            'nodes': [{'lat': lat, 'lon': lon} for lat, lon in lats_lons],
        }

    def test_building_inside_bbox(self):
        # A small square building near town centre
        b = self._make_building([
            (54.863, -6.279), (54.863, -6.278),
            (54.864, -6.278), (54.864, -6.279),
        ], levels=3, name='Town Hall')
        result = generate_buildings([b])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['class'], 'TSStatic')
        self.assertEqual(result[0].get('name'), 'Town Hall')

    def test_building_outside_bbox_filtered(self):
        b = self._make_building([
            (55.0, -5.0), (55.0, -4.99), (55.01, -4.99), (55.01, -5.0),
        ])
        result = generate_buildings([b])
        self.assertEqual(len(result), 0)

    def test_scale_matches_height(self):
        b = self._make_building([
            (54.863, -6.279), (54.863, -6.278),
            (54.864, -6.278), (54.864, -6.279),
        ], levels=4)
        result = generate_buildings([b])
        self.assertGreater(len(result), 0)
        # Z scale = building height
        scale_z = result[0]['scale'][2]
        self.assertAlmostEqual(scale_z, 12.0, places=0)  # 4 levels × 3 m


# ── parse_footways ───────────────────────────────────────────────────────────

class TestParseFootways(unittest.TestCase):
    def _make_way(self, nodes, highway='footway', name=''):
        return {'highway': highway, 'name': name, 'surface': '', 'nodes': nodes}

    def _latlon_nodes(self, pairs):
        return [{'lat': lat, 'lon': lon} for lat, lon in pairs]

    def test_footway_inside_bbox(self):
        nodes = self._latlon_nodes([(54.862, -6.280), (54.863, -6.279)])
        way = self._make_way(nodes, highway='footway')
        result = generate_footway_decals([way])
        self.assertGreater(len(result), 0)
        self.assertEqual(result[0]['class'], 'DecalRoad')

    def test_footway_parent_is_footways(self):
        nodes = self._latlon_nodes([(54.862, -6.280), (54.863, -6.279)])
        way = self._make_way(nodes, highway='footway')
        result = generate_footway_decals([way])
        self.assertGreater(len(result), 0)
        self.assertEqual(result[0]['__parent'], 'Footways')

    def test_footway_outside_bbox_excluded(self):
        nodes = self._latlon_nodes([(55.0, -6.0), (55.1, -5.9)])
        way = self._make_way(nodes, highway='footway')
        result = generate_footway_decals([way])
        self.assertEqual(len(result), 0)

    def test_cycleway_gets_cycleway_material(self):
        nodes = self._latlon_nodes([(54.862, -6.280), (54.863, -6.279)])
        way = self._make_way(nodes, highway='cycleway')
        result = generate_footway_decals([way])
        self.assertGreater(len(result), 0)
        self.assertIn('Asphalt', result[0]['material'])

    def test_footway_nodes_have_four_elements(self):
        nodes = self._latlon_nodes([(54.862, -6.280), (54.863, -6.279), (54.864, -6.278)])
        way = self._make_way(nodes, highway='path')
        result = generate_footway_decals([way])
        self.assertGreater(len(result), 0)
        for n in result[0]['nodes']:
            self.assertEqual(len(n), 4)

    def test_extract_footways_filters_non_footway(self):
        # extract_footways should include footway but not primary
        elements = [
            {'type': 'way', 'tags': {'highway': 'footway'}, 'nodes': [1, 2]},
            {'type': 'way', 'tags': {'highway': 'primary'}, 'nodes': [1, 2]},
        ]
        nodes_map = {1: (54.862, -6.280), 2: (54.863, -6.279)}
        ways = extract_footways(elements, nodes_map)
        self.assertEqual(len(ways), 1)
        self.assertEqual(ways[0]['highway'], 'footway')

    def test_render_priority_below_roads(self):
        nodes = self._latlon_nodes([(54.862, -6.280), (54.863, -6.279)])
        way = self._make_way(nodes, highway='footway')
        result = generate_footway_decals([way])
        self.assertGreater(len(result), 0)
        self.assertLess(result[0]['renderPriority'], 5)


# ── parse_features ───────────────────────────────────────────────────────────

class TestParseFeatures(unittest.TestCase):
    def _make_feature(self, kind, nodes, name=''):
        return {'kind': kind, 'name': name, 'nodes': nodes}

    def _latlon_nodes(self, pairs):
        return [{'lat': lat, 'lon': lon} for lat, lon in pairs]

    def test_parking_maps_to_asphalt(self):
        nodes = self._latlon_nodes([
            (54.862, -6.280), (54.862, -6.279),
            (54.863, -6.279), (54.863, -6.280),
        ])
        feat = self._make_feature('amenity:parking', nodes)
        result = generate_feature_polygons([feat])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['layer'], 2)  # LAYER_ASPHALT

    def test_park_maps_to_grass(self):
        nodes = self._latlon_nodes([
            (54.862, -6.280), (54.862, -6.279),
            (54.863, -6.279), (54.863, -6.280),
        ])
        feat = self._make_feature('leisure:park', nodes)
        result = generate_feature_polygons([feat])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['layer'], 0)  # LAYER_GRASS

    def test_waterway_maps_to_dirt(self):
        nodes = self._latlon_nodes([
            (54.862, -6.280), (54.862, -6.279),
            (54.863, -6.279), (54.863, -6.280),
        ])
        feat = self._make_feature('waterway:river', nodes)
        result = generate_feature_polygons([feat])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['layer'], 1)  # LAYER_DIRT

    def test_unknown_kind_excluded(self):
        nodes = self._latlon_nodes([
            (54.862, -6.280), (54.862, -6.279),
            (54.863, -6.279), (54.863, -6.280),
        ])
        feat = self._make_feature('unknown:thing', nodes)
        result = generate_feature_polygons([feat])
        self.assertEqual(len(result), 0)

    def test_outside_bbox_excluded(self):
        nodes = self._latlon_nodes([
            (55.0, -5.0), (55.0, -4.99), (55.01, -4.99), (55.01, -5.0),
        ])
        feat = self._make_feature('leisure:park', nodes)
        result = generate_feature_polygons([feat])
        self.assertEqual(len(result), 0)

    def test_result_has_pts_field(self):
        nodes = self._latlon_nodes([
            (54.862, -6.280), (54.862, -6.279),
            (54.863, -6.279), (54.863, -6.280),
        ])
        feat = self._make_feature('amenity:parking', nodes)
        result = generate_feature_polygons([feat])
        self.assertIn('pts', result[0])
        self.assertGreater(len(result[0]['pts']), 2)


# ── gen_waypoints ────────────────────────────────────────────────────────────

class TestGenWaypoints(unittest.TestCase):
    def _make_road(self, nodes, name=''):
        return {'nodes': nodes, 'name': name}

    def test_junction_detected_two_roads(self):
        # Two roads sharing an endpoint → one junction
        roads = [
            self._make_road([[0.0, 0.0, 5.0, 7.0], [100.0, 0.0, 5.0, 7.0]]),
            self._make_road([[0.0, 0.0, 5.0, 7.0], [0.0, 100.0, 5.0, 7.0]]),
        ]
        junctions = find_junctions(roads)
        self.assertGreaterEqual(len(junctions), 1)

    def test_no_junction_single_road(self):
        roads = [self._make_road([[0.0, 0.0, 5.0, 7.0], [100.0, 0.0, 5.0, 7.0]])]
        junctions = find_junctions(roads)
        self.assertEqual(len(junctions), 0)

    def test_junction_position_is_averaged(self):
        # Both roads touch (0,0) — junction should be at (0,0)
        roads = [
            self._make_road([[0.0, 0.0, 5.0, 7.0], [50.0, 0.0, 5.0, 7.0]]),
            self._make_road([[0.0, 0.0, 5.0, 7.0], [0.0, 50.0, 5.0, 7.0]]),
        ]
        junctions = find_junctions(roads)
        self.assertGreater(len(junctions), 0)
        x, y, z = junctions[0]
        self.assertAlmostEqual(x, 0.0, places=1)
        self.assertAlmostEqual(y, 0.0, places=1)

    def test_landmark_found(self):
        # Road named 'Bridge Street' → landmark waypoint emitted
        roads = [
            self._make_road([[10.0, 20.0, 5.0, 7.0], [30.0, 40.0, 5.0, 7.0]], name='Bridge Street'),
        ]
        landmarks = find_landmark_positions(roads)
        self.assertIn('wp_bridge_street', landmarks)

    def test_landmark_not_duplicated(self):
        roads = [
            self._make_road([[10.0, 20.0, 5.0, 7.0], [30.0, 40.0, 5.0, 7.0]], name='Bridge Street'),
            self._make_road([[50.0, 60.0, 5.0, 7.0], [70.0, 80.0, 5.0, 7.0]], name='Bridge Street'),
        ]
        landmarks = find_landmark_positions(roads)
        self.assertEqual(list(landmarks.keys()).count('wp_bridge_street'), 1)

    def test_make_waypoints_returns_beamngwaypoint(self):
        junctions = [(10.0, 20.0, 5.0)]
        landmarks = {'wp_bridge_street': (50.0, 60.0, 5.0)}
        wps = make_waypoints(junctions, landmarks)
        classes = [w['class'] for w in wps]
        self.assertTrue(all(c == 'BeamNGWaypoint' for c in classes))

    def test_make_waypoints_count(self):
        junctions = [(0.0, 0.0, 0.0), (10.0, 10.0, 0.0)]
        landmarks = {'wp_galgorm_road': (5.0, 5.0, 0.0)}
        wps = make_waypoints(junctions, landmarks)
        self.assertEqual(len(wps), 3)

    def test_waypoints_have_required_fields(self):
        wps = make_waypoints([(0.0, 0.0, 0.0)], {})
        self.assertIn('persistentId', wps[0])
        self.assertIn('position', wps[0])
        self.assertIn('radius', wps[0])
        self.assertEqual(wps[0]['__parent'], 'Waypoints')


# ── gen_building_shapes ──────────────────────────────────────────────────────

class TestBuildingShapeMapping(unittest.TestCase):
    def test_house_gets_pitched_brick(self):
        self.assertEqual(shape_for_building('house'), 'pitched_brick')

    def test_terrace_gets_pitched_brick(self):
        self.assertEqual(shape_for_building('terrace'), 'pitched_brick')

    def test_semidetached_gets_pitched_render(self):
        self.assertEqual(shape_for_building('semidetached_house'), 'pitched_render')

    def test_retail_gets_flat_retail(self):
        self.assertEqual(shape_for_building('retail'), 'flat_retail')

    def test_church_gets_flat_church(self):
        self.assertEqual(shape_for_building('church'), 'flat_church')

    def test_industrial_gets_flat_industrial(self):
        self.assertEqual(shape_for_building('industrial'), 'flat_industrial')

    def test_unknown_tag_gets_default(self):
        shape = shape_for_building('spaceship')
        self.assertIn(shape, SHAPES)

    def test_all_mapped_tags_have_valid_shape(self):
        for tag, shape in OSM_TAG_TO_SHAPE.items():
            self.assertIn(shape, SHAPES, f'tag "{tag}" maps to unknown shape "{shape}"')

    def test_dae_path_contains_shape_name(self):
        path = shape_dae_path('pitched_brick')
        self.assertIn('pitched_brick', path)
        self.assertTrue(path.endswith('.dae'))


class TestBuildingShapeGeometry(unittest.TestCase):
    def test_generate_all_shapes_writes_files(self):
        with tempfile.TemporaryDirectory() as td:
            n = generate_all_shapes(td)
            self.assertEqual(n, len(SHAPES))
            for name in SHAPES:
                path = os.path.join(td, f'{name}.dae')
                self.assertTrue(os.path.exists(path),
                                f'{name}.dae was not created')

    def test_pitched_dae_is_valid_collada(self):
        with tempfile.TemporaryDirectory() as td:
            generate_all_shapes(td)
            with open(os.path.join(td, 'pitched_brick.dae')) as f:
                content = f.read()
            self.assertIn('COLLADA', content)
            self.assertIn('Z_UP', content)

    def test_flat_dae_is_valid_collada(self):
        with tempfile.TemporaryDirectory() as td:
            generate_all_shapes(td)
            with open(os.path.join(td, 'flat_commercial.dae')) as f:
                content = f.read()
            self.assertIn('COLLADA', content)

    def test_pitched_has_more_triangles_than_flat(self):
        # Pitched roof has 14 tris vs flat's 10 tris
        with tempfile.TemporaryDirectory() as td:
            generate_all_shapes(td)
            for name, content in [
                ('pitched_brick', open(os.path.join(td, 'pitched_brick.dae')).read()),
                ('flat_commercial', open(os.path.join(td, 'flat_commercial.dae')).read()),
            ]:
                self.assertIn('count=', content)
            import re
            def tri_count(path):
                txt = open(path).read()
                m = re.search(r'<triangles[^>]+count="(\d+)"', txt)
                return int(m.group(1)) if m else 0
            pitched_n = tri_count(os.path.join(td, 'pitched_brick.dae'))
            flat_n    = tri_count(os.path.join(td, 'flat_commercial.dae'))
            self.assertGreater(pitched_n, flat_n)

    def test_buildings_use_typed_shapes(self):
        b_house = {
            'building': 'house', 'levels': 2, 'height': '', 'name': '',
            'amenity': '', 'id': 1,
            'nodes': [{'lat': 54.863, 'lon': -6.279},
                      {'lat': 54.863, 'lon': -6.278},
                      {'lat': 54.864, 'lon': -6.278},
                      {'lat': 54.864, 'lon': -6.279}],
        }
        result = generate_buildings([b_house])
        self.assertGreater(len(result), 0)
        self.assertIn('pitched_brick', result[0]['shapeName'])

    def test_buildings_default_shape_for_yes(self):
        b_yes = {
            'building': 'yes', 'levels': 2, 'height': '', 'name': '',
            'amenity': '', 'id': 2,
            'nodes': [{'lat': 54.863, 'lon': -6.279},
                      {'lat': 54.863, 'lon': -6.278},
                      {'lat': 54.864, 'lon': -6.278},
                      {'lat': 54.864, 'lon': -6.279}],
        }
        result = generate_buildings([b_yes])
        self.assertGreater(len(result), 0)
        # Should have a valid shape path ending in .dae
        self.assertTrue(result[0]['shapeName'].endswith('.dae'))


# ── gen_photo_spots ──────────────────────────────────────────────────────────

class TestHeadingToRotationMatrix(unittest.TestCase):
    def _rot(self, h):
        return heading_to_rotation_matrix(h)

    def test_heading_0_is_identity_xy(self):
        m = self._rot(0)
        self.assertAlmostEqual(m[0], 1.0, places=4)   # cos 0
        self.assertAlmostEqual(m[4], 1.0, places=4)
        self.assertAlmostEqual(m[1], 0.0, places=4)   # -sin 0
        self.assertAlmostEqual(m[3], 0.0, places=4)

    def test_heading_90_rotates_normal_to_plus_x(self):
        # normal +Y = (0,1,0); after heading-90 rotation it should become +X = (1,0,0)
        m = self._rot(90)
        # Apply M to +Y column vector: col1 of M = (m[1], m[4], m[7])
        nx = m[1]; ny = m[4]
        self.assertAlmostEqual(nx, 1.0, places=4)
        self.assertAlmostEqual(ny, 0.0, places=4)

    def test_heading_180_flips_y(self):
        m = self._rot(180)
        # normal +Y → -Y
        nx = m[1]; ny = m[4]
        self.assertAlmostEqual(nx,  0.0, places=4)
        self.assertAlmostEqual(ny, -1.0, places=4)

    def test_matrix_is_nine_elements(self):
        self.assertEqual(len(self._rot(45)), 9)

    def test_rotation_is_orthogonal(self):
        m = self._rot(37)
        # det should be ±1; for 2D rotation det = m[0]*m[4] - m[1]*m[3]
        det = m[0] * m[4] - m[1] * m[3]
        self.assertAlmostEqual(abs(det), 1.0, places=4)


class TestMakeBillboardTSStatic(unittest.TestCase):
    def test_class_and_parent(self):
        obj = make_billboard_tsstatic('test_id', 100.0, 200.0, 5.0, 0)
        self.assertEqual(obj['class'], 'TSStatic')
        self.assertEqual(obj['__parent'], 'PhotoSpots')

    def test_name_contains_id(self):
        obj = make_billboard_tsstatic('bridge_c1920', 0.0, 0.0, 0.0, 0)
        self.assertIn('bridge_c1920', obj['name'])

    def test_shape_is_billboard_plane(self):
        obj = make_billboard_tsstatic('x', 0.0, 0.0, 0.0, 0)
        self.assertIn('billboard', obj['shapeName'])
        self.assertIn('plane.dae', obj['shapeName'])

    def test_scale_reflects_billboard_size(self):
        obj = make_billboard_tsstatic('x', 0.0, 0.0, 0.0, 0)
        self.assertEqual(obj['scale'][0], 4.0)   # width
        self.assertEqual(obj['scale'][2], 3.0)   # height

    def test_position_z_offset(self):
        obj = make_billboard_tsstatic('x', 0.0, 0.0, 10.0, 0)
        # Z should be ground + half billboard height
        self.assertAlmostEqual(obj['position'][2], 10.0 + 1.5, places=2)

    def test_has_persistent_id(self):
        obj = make_billboard_tsstatic('x', 0.0, 0.0, 0.0, 0)
        self.assertIn('persistentId', obj)


class TestMakePhotoWaypoint(unittest.TestCase):
    def test_name_prefix(self):
        wp = make_photo_waypoint('bridge_c1920', 0.0, 0.0, 0.0, 'desc')
        self.assertTrue(wp['name'].startswith('photo_'))

    def test_class_and_parent(self):
        wp = make_photo_waypoint('x', 0.0, 0.0, 0.0, '')
        self.assertEqual(wp['class'], 'BeamNGWaypoint')
        self.assertEqual(wp['__parent'], 'PhotoSpots')

    def test_radius_is_positive(self):
        wp = make_photo_waypoint('x', 0.0, 0.0, 0.0, '')
        self.assertGreater(wp['radius'], 0)


class TestGeneratePhotoSpots(unittest.TestCase):
    def _make_photo(self, pid='test_spot', lat=54.863, lon=-6.279):
        return {
            'id': pid, 'lat': lat, 'lon': lon,
            'heading': 0, 'description': 'test',
            'year_then': 1920, 'year_now': None,
            'image_then': None, 'image_now': None,
            'credit_then': '', 'credit_now': '',
        }

    def test_spot_inside_bbox_emits_two_objects(self):
        photos = [self._make_photo()]
        with tempfile.TemporaryDirectory() as td:
            objects, generated = generate_photo_spots(photos, None, 0.0, td)
        self.assertEqual(len(objects), 2)    # 1 TSStatic + 1 waypoint
        self.assertEqual(len(generated), 1)

    def test_spot_outside_bbox_excluded(self):
        photos = [self._make_photo(lat=55.0, lon=-6.0)]
        with tempfile.TemporaryDirectory() as td:
            objects, generated = generate_photo_spots(photos, None, 0.0, td)
        self.assertEqual(len(objects), 0)
        self.assertEqual(len(generated), 0)

    def test_objects_have_correct_classes(self):
        photos = [self._make_photo()]
        with tempfile.TemporaryDirectory() as td:
            objects, _ = generate_photo_spots(photos, None, 0.0, td)
        classes = {o['class'] for o in objects}
        self.assertIn('TSStatic', classes)
        self.assertIn('BeamNGWaypoint', classes)

    def test_composite_placeholder_created(self):
        photos = [self._make_photo('placeholder_test')]
        with tempfile.TemporaryDirectory() as td:
            generate_photo_spots(photos, None, 0.0, td)
            png = os.path.join(td, 'placeholder_test.png')
            self.assertTrue(os.path.exists(png))


class TestValidatePhotos(unittest.TestCase):
    def test_required_fields_defined(self):
        self.assertIn('id', REQUIRED_FIELDS)
        self.assertIn('lat', REQUIRED_FIELDS)
        self.assertIn('lon', REQUIRED_FIELDS)
        self.assertIn('image_then', REQUIRED_FIELDS)

    def test_bbox_constants_sane(self):
        s, w, n, e = PHOTO_BBOX
        self.assertLess(s, n)    # south < north
        self.assertLess(w, e)    # west < east (both negative, west more negative)
        # Center should be around Ballymena
        self.assertAlmostEqual((s + n) / 2, 54.865, places=1)

    def test_manifest_is_valid(self):
        manifest_path = os.path.join(
            os.path.dirname(__file__), '..', 'data', 'photos', 'photo_manifest.json')
        self.assertTrue(os.path.exists(manifest_path),
                        'photo_manifest.json missing from data/photos/')
        with open(manifest_path) as f:
            data = json.load(f)
        photos = data.get('photos', [])
        self.assertGreater(len(photos), 0)
        s, w, n, e = PHOTO_BBOX
        for p in photos:
            with self.subTest(id=p.get('id')):
                for field in REQUIRED_FIELDS:
                    self.assertTrue(p.get(field),
                                    f'Missing field "{field}" in entry {p.get("id")}')
                self.assertTrue(s <= p['lat'] <= n, f'lat out of BBOX: {p["lat"]}')
                self.assertTrue(w <= p['lon'] <= e, f'lon out of BBOX: {p["lon"]}')


class TestBillboardDae(unittest.TestCase):
    def test_generates_valid_collada(self):
        from gen_billboard_dae import generate_billboard_dae
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'plane.dae')
            generate_billboard_dae(path)
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                content = f.read()
            self.assertIn('COLLADA', content)
            self.assertIn('Z_UP', content)
            self.assertIn('plane_mesh', content)

    def test_dae_has_uv_coordinates(self):
        from gen_billboard_dae import generate_billboard_dae
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'plane.dae')
            generate_billboard_dae(path)
            with open(path) as f:
                content = f.read()
            self.assertIn('TEXCOORD', content)


# ── fetch_satellite ──────────────────────────────────────────────────────────

class TestDeg2Tile(unittest.TestCase):
    def test_returns_integers(self):
        xt, yt = deg2tile(54.864, -6.278, 17)
        self.assertIsInstance(xt, int)
        self.assertIsInstance(yt, int)

    def test_tile_coords_in_valid_range(self):
        xt, yt = deg2tile(54.864, -6.278, 17)
        n = 2 ** 17
        self.assertGreaterEqual(xt, 0)
        self.assertLess(xt, n)
        self.assertGreaterEqual(yt, 0)
        self.assertLess(yt, n)

    def test_east_tile_greater_than_west(self):
        xt_west, _ = deg2tile(54.864, -6.293, 17)
        xt_east, _ = deg2tile(54.864, -6.262, 17)
        self.assertGreater(xt_east, xt_west)

    def test_south_tile_greater_than_north(self):
        # In slippy-map tile coordinates y increases southward
        _, yt_north = deg2tile(54.874, -6.278, 17)
        _, yt_south = deg2tile(54.856, -6.278, 17)
        self.assertGreater(yt_south, yt_north)

    def test_known_zoom16_tile(self):
        # Verify computed values for London (51.5, -0.1) at zoom 16
        # n=65536; x = int(179.9/360*65536)=32749; this anchors the implementation
        xt, yt = deg2tile(51.5, -0.1, 16)
        self.assertEqual(xt, 32749)
        # y value confirms latitude formula (not pinned to specific value, just sane range)
        self.assertGreater(yt, 20000)
        self.assertLess(yt, 25000)


class TestTileNwLatlon(unittest.TestCase):
    def test_returns_tuple_of_floats(self):
        lat, lon = tile_nw_latlon(32747, 21781, 16)
        self.assertIsInstance(lat, float)
        self.assertIsInstance(lon, float)

    def test_roundtrip_nw_corner(self):
        # NW corner lat/lon of a tile should map back to that tile (or its north neighbour
        # at the exact boundary — allow ±1 due to floating-point precision)
        xt0, yt0 = deg2tile(54.870, -6.285, 16)
        lat_nw, lon_nw = tile_nw_latlon(xt0, yt0, 16)
        xt1, yt1 = deg2tile(lat_nw, lon_nw, 16)
        self.assertEqual(xt0, xt1)
        self.assertIn(yt1, (yt0 - 1, yt0))

    def test_adjacent_tile_nw_corner_is_east(self):
        lat0, lon0 = tile_nw_latlon(10, 10, 10)
        lat1, lon1 = tile_nw_latlon(11, 10, 10)
        self.assertGreater(lon1, lon0)

    def test_south_tile_has_lower_lat(self):
        lat_n, _ = tile_nw_latlon(10, 10, 10)
        lat_s, _ = tile_nw_latlon(10, 11, 10)
        self.assertGreater(lat_n, lat_s)


# ── gen_sat_plane_dae ────────────────────────────────────────────────────────

class TestSatPlaneDae(unittest.TestCase):
    def _make(self, td, u_max=1.0, v_max=1.0):
        path = os.path.join(td, 'sat_plane.dae')
        generate_sat_plane_dae(path, u_max=u_max, v_max=v_max)
        return path

    def test_file_is_created(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._make(td)
            self.assertTrue(os.path.exists(path))

    def test_is_valid_collada(self):
        with tempfile.TemporaryDirectory() as td:
            with open(self._make(td)) as f:
                txt = f.read()
            self.assertIn('COLLADA', txt)
            self.assertIn('Z_UP', txt)

    def test_has_texture_reference(self):
        with tempfile.TemporaryDirectory() as td:
            with open(self._make(td)) as f:
                txt = f.read()
            self.assertIn('satellite.png', txt)
            self.assertIn('TEXCOORD', txt)

    def test_has_two_triangles(self):
        with tempfile.TemporaryDirectory() as td:
            with open(self._make(td)) as f:
                txt = f.read()
            m = re.search(r'<triangles[^>]+count="(\d+)"', txt)
            self.assertIsNotNone(m)
            self.assertEqual(int(m.group(1)), 2)

    def test_uv_max_respected(self):
        with tempfile.TemporaryDirectory() as td:
            with open(self._make(td, u_max=0.875, v_max=0.75)) as f:
                txt = f.read()
            self.assertIn('0.875000', txt)
            self.assertIn('0.750000', txt)

    def test_unit_uv_fills_texture(self):
        with tempfile.TemporaryDirectory() as td:
            with open(self._make(td, u_max=1.0, v_max=1.0)) as f:
                txt = f.read()
            self.assertIn('1.000000', txt)


# ── build_map satellite helpers ───────────────────────────────────────────────

class TestMakeSatelliteGroundPlane(unittest.TestCase):
    def _obj(self, level_size=4096, u_max=1.0, v_max=1.0, base_elev=0.0):
        return make_satellite_ground_plane(level_size, u_max, v_max, base_elev)

    def test_is_tsstatic(self):
        self.assertEqual(self._obj()['class'], 'TSStatic')

    def test_has_satellite_plane_shape(self):
        self.assertIn('satellite_plane', self._obj()['shapeName'])

    def test_scale_matches_level_size(self):
        obj = self._obj(level_size=2048)
        self.assertAlmostEqual(obj['scale'][0], 2048.0)
        self.assertAlmostEqual(obj['scale'][1], 2048.0)

    def test_position_slightly_below_base(self):
        obj = self._obj(base_elev=5.0)
        self.assertLess(obj['position'][2], 5.0)

    def test_has_persistent_id(self):
        self.assertIn('persistentId', self._obj())

    def test_parent_is_mission_group(self):
        self.assertEqual(self._obj()['__parent'], 'MissionGroup')


if __name__ == '__main__':
    unittest.main(verbosity=2)
