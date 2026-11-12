"""Tests for rotate.py. Run from the repo root with:  python -m unittest"""
import argparse
import contextlib
import io
import json
import random
import shutil
import subprocess
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

    def test_zones_have_exactly_one_default(self):
        for name, m in self.catalog["maps"].items():
            defaults = [z for z in m["zones"] if rotate.is_default_zone(z)]
            self.assertEqual(len(defaults), 1, f"{name}: list either '' or the explicit Default zone, not both")
            if "" in m["zones"]:
                self.assertEqual(m["zones"], [""], f"{name}: '' is only for maps with no zone alternators")


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

    def test_rejects_unknown_modifier(self):
        obj = json.loads((ROOT / "examples" / "export-modifiers.json").read_text(encoding="utf-8"))
        obj["entries"][0]["modifiers"] = ["KOTH_NoSnipers"]
        self.assertTrue(rotate.validate_rotation(obj, self.catalog))

    def test_rejects_extra_keys(self):
        obj = json.loads((ROOT / "examples" / "export-all-options.json").read_text(encoding="utf-8"))
        obj["entries"][0]["extra"] = 1
        self.assertTrue(rotate.validate_rotation(obj, self.catalog))


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = rotate.load_catalog()
        self.pool = rotate.build_pool(self.catalog)

    def pick(self, count=20, seed=1, modifiers=(), **filters):
        pool = rotate.build_pool(self.catalog, modifiers)
        pool = rotate.filter_pool(pool, self.catalog, make_args(**filters))
        return rotate.pick_entries(pool, count, random.Random(seed), False)

    def test_default_is_standard_game_mode(self):
        self.assertTrue(all(p["entry"]["modifiers"] == [] for p in self.pick(count=30)))

    def test_modifiers_apply_to_every_map_in_catalog_order(self):
        for chosen, expected in [(["InfantryOnly"], ["KOTH_InfantryOnly"]),
                                 (["Hardcore"], ["KOTH_Hardcore"]),
                                 (["Hardcore", "InfantryOnly"], ["KOTH_InfantryOnly", "KOTH_Hardcore"])]:
            with self.subTest(chosen=chosen):
                picks = self.pick(count=30, modifiers=chosen)
                self.assertEqual({tuple(p["entry"]["modifiers"]) for p in picks}, {tuple(expected)})

    def test_sabatulo_only_uses_its_lighting(self):
        allowed = {"DayClear", "DayLateClear", "DayLateGray", "DayLateRain"}
        picks = self.pick(count=12, maps=["Sabatulo"], modifiers=["LimitedGear"])
        for p in picks:
            self.assertEqual(p["entry"]["map"], "Russia")
            self.assertEqual(p["entry"]["experience"], "Moscow_KOTH_01")
            self.assertIn(p["entry"]["lighting"], allowed)
            self.assertEqual(p["entry"]["modifiers"], ["KOTH_LimitedGear"])
        self.assertEqual({p["entry"]["lighting"] for p in picks}, allowed)

    def test_limited_gear_goes_after_other_modifiers(self):
        picks = self.pick(count=12, modifiers=["LimitedGear", "InfantryOnly"])
        self.assertEqual({tuple(p["entry"]["modifiers"]) for p in picks},
                         {("KOTH_InfantryOnly", "KOTH_LimitedGear")})
        self.assertEqual({p["display"] for p in picks}, set(self.catalog["maps"]))

    def test_resolve_modifiers(self):
        r = lambda *s: rotate.resolve_modifiers(self.catalog, list(s))  # noqa: E731
        self.assertEqual(r(), [])
        self.assertEqual(r("none"), [])
        self.assertEqual(r("infantry"), ["InfantryOnly"])
        self.assertEqual(r("KOTH_Hardcore", "hardcore"), ["Hardcore"])
        with self.assertRaises(rotate.RotationError):
            r("snipers")

    def test_no_back_to_back_maps_and_no_duplicates(self):
        picks = self.pick(count=30)
        maps = [p["display"] for p in picks]
        self.assertTrue(all(a != b for a, b in zip(maps, maps[1:])))
        keys = [rotate.entry_key(p["entry"]) for p in picks]
        self.assertEqual(len(keys), len(set(keys)))

    def count_maps(self, picks):
        counts = {}
        for p in picks:
            counts[p["display"]] = counts.get(p["display"], 0) + 1
        return counts

    def test_maps_are_balanced(self):
        # 16 maps fits within Sabatulo's 4 combinations, so every map gets 4.
        counts = self.count_maps(self.pick(count=16))
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_small_map_steps_aside_instead_of_repeating(self):
        counts = self.count_maps(self.pick(count=30))
        self.assertEqual(counts["Sabatulo"], 4)
        others = [v for k, v in counts.items() if k != "Sabatulo"]
        self.assertLessEqual(max(others) - min(others), 1)

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
                code = rotate.main(["--count", "12", "--name", "Test", "--out", str(out), "--seed", "3",
                                    "--modifiers", "infantry"])
            self.assertEqual(code, 0)
            obj = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(list(obj), rotate.TOP_KEYS)
            self.assertEqual(list(obj["entries"][0]), rotate.ENTRY_KEYS)
            self.assertEqual(len(obj["entries"]), 12)
            self.assertTrue(all(e["modifiers"] == ["KOTH_InfantryOnly"] for e in obj["entries"]))
            self.assertEqual(rotate.validate_rotation(obj, rotate.load_catalog()), [])

    def test_default_filename(self):
        self.assertEqual(rotate.default_out("Rotation 2026").name, "rotation-2026.json")
        self.assertEqual(rotate.default_out("Night Ops").name, "rotation-night-ops.json")


@unittest.skipUnless(shutil.which("node"), "Node.js not installed; web logic not tested")
class WebParityTests(unittest.TestCase):
    """Runs the website's generator (web/rotation.js) and checks it against the same rules."""

    def generate(self, **opts):
        out = subprocess.run(["node", str(ROOT / "tests" / "web_generate.mjs"), json.dumps(opts)],
                             capture_output=True, text=True, encoding="utf-8", check=True).stdout
        return json.loads(out)

    def test_web_output_is_valid_and_follows_rules(self):
        catalog = rotate.load_catalog()
        internal = {m["map"]: d for d, m in catalog["maps"].items()}
        legacy = {mode["experience"] for m in catalog["maps"].values()
                  for mode in m["modes"].values() if mode.get("legacy")}
        cases = [dict(count=30, seed=1),
                 dict(count=12, seed=2, modifiers=["InfantryOnly"]),
                 dict(count=12, seed=3, modifiers=["Hardcore", "InfantryOnly"], maps=["Ozeti", "Bakurani"]),
                 dict(count=40, seed=4, includeLegacy=True)]
        for opts in cases:
            with self.subTest(opts=opts):
                rot = self.generate(**opts)
                self.assertEqual(rotate.validate_rotation(rot, catalog), [])
                entries = rot["entries"]
                self.assertEqual(len(entries), opts["count"])
                maps = [internal[e["map"]] for e in entries]
                self.assertTrue(all(a != b for a, b in zip(maps, maps[1:])))
                self.assertEqual(len({rotate.entry_key(e) for e in entries}), len(entries))
                self.assertEqual(len({tuple(e["modifiers"]) for e in entries}), 1)
                if opts.get("maps"):
                    self.assertTrue(set(maps) <= set(opts["maps"]))
                used_legacy = {e["experience"] for e in entries} & legacy
                self.assertEqual(bool(used_legacy), bool(opts.get("includeLegacy")))

    def test_web_writes_same_layout_as_python(self):
        rot = self.generate(count=3, seed=5)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.json"
            rotate.write_rotation(rot, out)
            text = subprocess.run(["node", str(ROOT / "tests" / "web_generate.mjs"),
                                   json.dumps(dict(count=3, seed=5))],
                                  capture_output=True, text=True, encoding="utf-8", check=True).stdout
            self.assertEqual(out.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
