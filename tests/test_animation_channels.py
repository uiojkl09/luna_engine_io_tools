"""Format regression checks; run with python -m unittest discover -s tests."""
import importlib.util
import math
from pathlib import Path
import random
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "luna_animation_tests", ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
luna = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = luna
spec.loader.exec_module(luna)
morph = sys.modules[spec.name + ".anim_morph"]
export = sys.modules[spec.name + ".anim_export"]


class MorphTrackTests(unittest.TestCase):
    def roundtrip(self, rows):
        targets = [{"name": f"Target_{i}", "hash": luna._registration.hashes.string_crc32(f"Target_{i}")}
                   for i in range(len(rows[0]))]
        encoded = morph.encode_anim_morph(targets, rows, name_offset_base=5)
        self.assertIsNotNone(encoded)
        decoded = morph.decode_anim_morph(encoded["info"], encoded["frame_data"], len(rows),
                                         b"clip\0" + encoded["strings"])
        columns = {t["hash"]: i for i, t in enumerate(targets)}
        for frame, row in enumerate(decoded["samples"]):
            for i, target in enumerate(decoded["targets"]):
                self.assertAlmostEqual(row[i], rows[frame][columns[target["hash"]]],
                                       delta=encoded["quantization_error_bound"] + 1e-6)
        self.assertEqual([t["hash"] for t in decoded["targets"]],
                         sorted(t["hash"] for t in encoded["targets"]))
        return encoded

    def test_zero_one_zero(self):
        self.roundtrip([[0], [1], [0]])

    def test_constant_and_single_sample(self):
        self.roundtrip([[0.75]] * 4)
        self.roundtrip([[0.5]])

    def test_signed_multiple_targets(self):
        self.roundtrip([[0, 0, 1], [1, -1, 0], [0.5, 0.1, 0.25], [0, 0, 0]])

    def test_large_target_table(self):
        rng = random.Random(30)
        self.roundtrip([[rng.uniform(-1.5, 2.5) for _ in range(255)] for _ in range(9)])

    def test_all_zero_tracks_omitted(self):
        self.assertIsNone(morph.encode_anim_morph([{"name": "Zero", "hash": 1}], [[0], [0]]))

    def test_nonfinite_values_rejected(self):
        for value in (math.inf, math.nan):
            with self.subTest(value=value), self.assertRaises(ValueError):
                morph.encode_anim_morph([{"name": "Bad", "hash": 1}], [[value]])

    def test_truncated_sections_rejected(self):
        encoded = self.roundtrip([[0], [1], [0]])
        for info, data in ((encoded["info"][:23], encoded["frame_data"]),
                           (encoded["info"], encoded["frame_data"][:1])):
            with self.assertRaises(ValueError):
                morph.decode_anim_morph(info, data, 3)

    def test_colliding_hashes_rejected(self):
        with self.assertRaises(ValueError):
            morph.encode_anim_morph([{"name": "A", "hash": 1}, {"name": "B", "hash": 1}], [[1, 1]])

    def test_native_sentinel_rejected(self):
        with self.assertRaises(ValueError):
            morph.encode_anim_morph([{"name": "Sentinel", "hash": 0xffffffff}], [[1]])


class BoneScaleTests(unittest.TestCase):
    def test_fixed_point_range(self):
        self.assertEqual(export._compute_scale_log_scale([(1, 1, 1)]), 12)
        self.assertLess(export._compute_scale_log_scale([(100, 1, 1)]), 12)
        for scale in ((-1, 1, 1), (math.nan, 1, 1), (100000, 1, 1)):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                export._compute_scale_log_scale([scale])

    def test_native_base_scale_groups(self):
        # Five non-unit joints require two 32-byte native four-joint records.
        pose = [[1024, 2048, 3072] + [0] * 9 for _ in range(5)]
        data, count = export._pack_base_scale_groups(pose, [12] * 5)
        self.assertEqual(count, 2)
        self.assertEqual(len(data), 64)
        first = struct.unpack_from("<16H", data)
        self.assertEqual(first[6:8], (0, 48))
        last = struct.unpack_from("<16H", data, 32)
        self.assertEqual(last[6:8], (192, 192))


if __name__ == "__main__":
    unittest.main()
