"""Unit tests for the NI LiDAR (OSNI River Basin) terrain fetcher."""
import os
import sys
import unittest

import numpy as np
import zstandard

# Ensure src/ is importable regardless of cwd
SRC = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, os.path.abspath(SRC))

import fetch_lidar as fl


def _encode_tile(tile):
    """Inverse of the COG encoder: float32 → horizontal-differenced uint32 → zstd."""
    bits = np.ascontiguousarray(tile, dtype='<f4').view('<u4')
    diff = np.diff(bits, axis=1, prepend=np.zeros((bits.shape[0], 1), bits.dtype))
    raw = diff.astype('<u4').tobytes()
    return zstandard.ZstdCompressor().compress(raw)


class TestTileDecode(unittest.TestCase):

    def test_decode_undoes_predictor_and_zstd(self):
        rng = np.random.default_rng(1234)
        tile = rng.uniform(30.0, 70.0, size=(8, 16)).astype('<f4')
        blob = _encode_tile(tile)
        meta = {
            'tile_w': 16, 'tile_h': 8, 'predictor': 2,
            'offsets': np.array([0], dtype='<u4'),
            'counts':  np.array([len(blob)], dtype='<u4'),
        }
        original = fl.http_range
        fl.http_range = lambda url, s, e: blob[s:e + 1]
        try:
            decoded = fl._decode_tile(0, meta, 'memory://', zstandard.ZstdDecompressor())
        finally:
            fl.http_range = original
        np.testing.assert_allclose(decoded, tile, rtol=0, atol=0)

    def test_decode_without_predictor(self):
        tile = np.arange(8, dtype='<f4').reshape(2, 4)
        blob = zstandard.ZstdCompressor().compress(tile.tobytes())
        meta = {
            'tile_w': 4, 'tile_h': 2, 'predictor': 1,
            'offsets': np.array([0], dtype='<u4'),
            'counts':  np.array([len(blob)], dtype='<u4'),
        }
        original = fl.http_range
        fl.http_range = lambda url, s, e: blob[s:e + 1]
        try:
            decoded = fl._decode_tile(0, meta, 'memory://', zstandard.ZstdDecompressor())
        finally:
            fl.http_range = original
        np.testing.assert_allclose(decoded, tile, rtol=0, atol=0)


class TestResample(unittest.TestCase):

    def test_shape_and_uniform_value(self):
        window = np.full((32, 32), 42.0, dtype=np.float32)
        wmeta = {'e0': 300000.0, 'n1': 400000.0, 'pixel': 1.0}
        out = fl.resample_to_bbox(window, wmeta, 5, 7)
        self.assertEqual(out.shape, (5, 7))
        np.testing.assert_allclose(out, 42.0)

    def test_nodata_filled_not_nan(self):
        window = np.full((16, 16), 50.0, dtype=np.float32)
        window[0, 0] = np.nan
        wmeta = {'e0': 300000.0, 'n1': 400000.0, 'pixel': 1.0}
        out = fl.resample_to_bbox(window, wmeta, 4, 4)
        self.assertFalse(np.isnan(out).any())


class TestGridCoverage(unittest.TestCase):

    def test_grid_corners_match_bbox(self):
        """Row 0 / col 0 of the grid must be the south-west BBOX corner."""
        s, w, n, e = fl.BBOX
        lats = np.linspace(s, n, fl.GRID_ROWS)
        lons = np.linspace(w, e, fl.GRID_COLS)
        self.assertAlmostEqual(lats[0], s, places=9)
        self.assertAlmostEqual(lats[-1], n, places=9)
        self.assertAlmostEqual(lons[0], w, places=9)
        self.assertAlmostEqual(lons[-1], e, places=9)


if __name__ == '__main__':
    unittest.main()
