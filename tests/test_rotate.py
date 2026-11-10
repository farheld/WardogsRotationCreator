"""Tests for rotate.py. Run from the repo root with:  python -m unittest"""
import argparse
import contextlib
import io
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rotate  # noqa: E402


def make_args(**overrides) -> argparse.Namespace:
    defaults = dict(
        maps=None, modes=None, modifiers=None, lighting=None, exclude_lighting=None,
        weather=None, exclude_weather=None, zones=None, exclude_zones=None,
        no_default_zone=False, default_zone_only=False, include_legacy=False,
        allow_repeats=False)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = rotate.load_catalog()

    def test_every_lighting_preset_has_tags(self):
        tags = self.catalog["lightingTags"]
        for name, m in self.catalog["maps"].items():
            for light in m["lighting"]:
                self.assertIn(light, tags, f"{name}: {light} has no lightingTags entry")

    def test_zones_are_explicit_and_have_a_default(self):
        for name, m in self.catalog["maps"].items():
            self.assertNotIn("", m["zones"], f"{name}: use the explicit Default zone, not ''")
            self.assertTrue(any(rotate.is_default_zone(z) for z in m["zones"]),
                            f"{name}: no Default zone listed")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = rotate.load_catalog()

    def test_dashboard_exports_are_valid(self):
        for path in sorted((ROOT / "examples").glob("*.json")):
            with self.subTest(path=path.name):
                obj = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(rotate.validate_rotation(obj, self.catalog), [])

    def test_rejects_unknown_combination(self):
        bad = rotate.build_rotation("x", "Ordered", [])
        bad["entries"] = [{"map": "Nowhere", "experience": "X", "modifiers": [],
                           "lighting": "DayClear", "zoneAlternator": ""}]
        self.assertTrue(rotate.validate_rotation(bad, self.catalog))

    def test_rejects_extra_keys(self):
        obj = json.loads((ROOT / "examples" / "export-all-options.json").read_text(encoding="utf-8"))
        obj["entries"][0]["extra"] = 1
        self.assertTrue(rotate.validate_rotation(obj, self.catalog))


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = rotate.load_catalog()
        self.pool = rotate.build_pool(self.catalog)

    def pick(self, count=20, seed=1, **filters):
        pool = rotate.filter_pool(self.pool, self.catalog, make_args(**filters))
        return rotate.pick_entries(pool, count, random.Random(seed), False)

    def test_no_back_to_back_maps_and_no_duplicates(self):
        picks = self.pick(count=30)
        maps = [p["display"] for p in picks]
        self.assertTrue(all(a != b for a, b in zip(maps, maps[1:])))
        keys = [rotate.entry_key(p["entry"]) for p in picks]
        self.assertEqual(len(keys), len(set(keys)))

    def test_maps_are_balanced(self):
        counts = {}
        for p in self.pick(count=30):
            counts[p["display"]] = counts.get(p["display"], 0) + 1
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_same_seed_same_rotation(self):
        self.assertEqual(self.pick(seed=42), self.pick(seed=42))

    def test_legacy_modes_are_opt_in(self):
        legacy = {mode["experience"] for m in self.catalog["maps"].values()
                  for mode in m["modes"].values() if mode.get("legacy")}
        used = {p["entry"]["experience"] for p in self.pick(count=60)}
        self.assertFalse(used & legacy)
        used = {p["entry"]["experience"] for p in self.pick(count=60, include_legacy=True)}
        self.assertTrue(used & legacy)

    def test_filters(self):
        picks = self.pick(count=8, maps=["Bakurani"], weather=["rain", "fog"], zones=["Farmland"])
        for p in picks:
            e = p["entry"]
            self.assertEqual(p["display"], "Bakurani")
            self.assertIn(e["lighting"], {"DayLateRain", "DayEarlyFog", "DayLateGrayFog"})
            self.assertTrue(e["zoneAlternator"].endswith(".Farmland.Circle"))

    def test_no_matches_raises(self):
        with self.assertRaises(rotate.RotationError):
            self.pick(maps=["Ozeti"], zones=["Lumberyard"])


class CommandLineTests(unittest.TestCase):
    def test_writes_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = rotate.main(["--count", "12", "--name", "Test", "--out", str(out), "--seed", "3"])
            self.assertEqual(code, 0)
            obj = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(list(obj), rotate.TOP_KEYS)
            self.assertEqual(list(obj["entries"][0]), rotate.ENTRY_KEYS)
            self.assertEqual(len(obj["entries"]), 12)
            self.assertEqual(rotate.validate_rotation(obj, rotate.load_catalog()), [])

    def test_default_filename(self):
        self.assertEqual(rotate.default_out("Rotation 2026").name, "rotation-2026.json")
        self.assertEqual(rotate.default_out("Night Ops").name, "rotation-night-ops.json")


if __name__ == "__main__":
    unittest.main()
