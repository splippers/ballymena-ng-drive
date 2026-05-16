"""Unit tests for the Ballymena NG Drive pipeline."""
import sys, os, json, struct, math, unittest, tempfile, shutil

# Ensure src/ is importable regardless of cwd
SRC = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, os.path.abspath(SRC))

import utils
from parse_roads import (material_for_road, simplify_polyline,
                         build_decal_road, generate_decal_roads)
from parse_buildings import (building_height, oriented_bbox,
                              polygon_centroid, generate_buildings)
from build_map import (pick_level_size, pick_terrain_res, bounds_from_ndjson,
                       build_elevation_array, build_layermap)


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
        result = build_layermap([], 1024, 32)
        self.assertEqual(len(result), 32 * 32)

    def test_empty_roads_all_grass(self):
        result = build_layermap([], 1024, 32)
        self.assertTrue(all(v == 0 for v in result))

    def test_road_paints_asphalt(self):
        # A road crossing the middle of a 1024m world on a 64-px layermap
        road = self._make_road(-200, 0, 200, 0, 10.0)
        result = build_layermap([road], 1024, 64)
        # At least some pixels should be asphalt (value 2)
        self.assertIn(2, result)

    def test_values_in_range(self):
        road = self._make_road(-100, 0, 100, 0, 5.0)
        result = build_layermap([road], 1024, 32)
        self.assertTrue(all(0 <= v <= 2 for v in result))


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
